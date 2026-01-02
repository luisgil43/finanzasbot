# owner_panel/views.py
from __future__ import annotations

from datetime import date, datetime
from functools import wraps
from typing import Iterable, Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import UserProfile
from subscriptions.models import BillingSettings, Plan, UserSubscription

User = get_user_model()

ROLE_ADMIN = "admin_general"
ROLE_FINANCE = "finance"
ROLE_SUPPORT = "support"
STAFF_GROUPS = [ROLE_ADMIN, ROLE_FINANCE, ROLE_SUPPORT]


# -----------------------------
# Helpers
# -----------------------------
def _get_profile(user) -> UserProfile:
    prof, _ = UserProfile.objects.get_or_create(user=user)
    return prof


def _get_billing_settings_for_owner(user) -> BillingSettings:
    """
    BillingSettings por owner (admin_general/superuser).
    Si hay varios admins, toma el primero; fallback al usuario actual.
    """
    owner = (
        User.objects.filter(is_superuser=True).order_by("id").first()
        or User.objects.filter(groups__name=ROLE_ADMIN).order_by("id").first()
        or user
    )
    obj, _ = BillingSettings.objects.get_or_create(owner=owner)
    return obj


def _has_any_staff_role(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=STAFF_GROUPS).exists()


def _is_admin_general(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=ROLE_ADMIN).exists()


def _roles_for_user(user) -> list[str]:
    if not user.is_authenticated:
        return []
    roles = set(user.groups.values_list("name", flat=True))
    if user.is_superuser:
        roles.add(ROLE_ADMIN)
    return [r for r in STAFF_GROUPS if r in roles]


def _dedupe_users(users: Iterable[User]) -> list[User]:
    seen = set()
    out = []
    for u in users:
        if u.id in seen:
            continue
        seen.add(u.id)
        out.append(u)
    return out


def _ensure_groups(names: list[str]) -> list[Group]:
    """
    Asegura que existan los groups staff, para evitar set([]) silencioso.
    """
    groups = []
    for n in names:
        g, _ = Group.objects.get_or_create(name=n)
        groups.append(g)
    return groups


def _get_plan_by_code(code: str) -> Optional[Plan]:
    code = (code or "").strip().lower()
    if code not in (Plan.CODE_FREE, Plan.CODE_PLUS, Plan.CODE_PRO):
        return None
    return (
        Plan.objects.filter(code=code, is_active=True).first()
        or Plan.objects.filter(code=code).first()
    )


def _get_or_create_active_subscription(u: User) -> UserSubscription:
    """
    Evita depender de métodos antiguos (get_or_create_for_user) y
    soporta el nuevo esquema: UserSubscription.plan = FK Plan.
    """
    sub = (
        UserSubscription.objects
        .filter(user=u, status=UserSubscription.STATUS_ACTIVE)
        .order_by("-started_at", "-id")
        .first()
    )
    if sub:
        return sub

    free = _get_plan_by_code(Plan.CODE_FREE) or Plan.objects.order_by("id").first()
    return UserSubscription.objects.create(
        user=u,
        plan=free,
        status=UserSubscription.STATUS_ACTIVE,
        started_at=timezone.now(),
    )


def _parse_date_yyyy_mm_dd(raw: str) -> Optional[date]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        yyyy, mm, dd = raw.split("-")
        return date(int(yyyy), int(mm), int(dd))
    except Exception:
        return None


def _end_of_day_aware(d: date):
    """
    Convierte YYYY-MM-DD a datetime aware 23:59:59 en TZ local.
    """
    dt = datetime(d.year, d.month, d.day, 23, 59, 59)
    tz = timezone.get_current_timezone()
    return timezone.make_aware(dt, tz)


# -----------------------------
# Decorators
# -----------------------------
def staff_required(view):
    """
    Acceso Owner Admin:
    - superuser
    - o usuario con group en (admin_general, finance, support)
    """
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")

        if _has_any_staff_role(request.user):
            return view(request, *args, **kwargs)

        messages.error(request, "No tienes permisos para acceder al Owner Admin.")
        return redirect("accounts:dashboard")

    return _wrapped


# -----------------------------
# Views
# -----------------------------
@staff_required
def dashboard(request):
    billing = _get_billing_settings_for_owner(request.user)
    can_manage = _is_admin_general(request.user)

    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Solo Admin General puede modificar Billing Settings.")
            return redirect("owner_panel:dashboard")

        action = request.POST.get("action") or ""

        if action == "toggle_billing":
            billing.billing_enabled = not bool(getattr(billing, "billing_enabled", False))
            billing.save(update_fields=["billing_enabled"])
            messages.success(
                request,
                "Cobro ACTIVADO ✅" if billing.billing_enabled else "Cobro DESACTIVADO 🧪"
            )
            return redirect("owner_panel:dashboard")

        if action == "set_go_live":
            d = _parse_date_yyyy_mm_dd(request.POST.get("go_live_date"))
            if not d:
                messages.error(request, "Fecha inválida. Usa formato YYYY-MM-DD.")
                return redirect("owner_panel:dashboard")

            billing.go_live_date = d
            billing.save(update_fields=["go_live_date"])
            messages.success(request, "Fecha de cobro guardada ✅")
            return redirect("owner_panel:dashboard")

        messages.error(request, "Acción no válida.")
        return redirect("owner_panel:dashboard")

    total_users = User.objects.count()
    total_active = User.objects.filter(is_active=True).count()

    # “Clientes” = no staff y no superuser
    total_customers = (
        User.objects
        .filter(is_superuser=False)
        .exclude(groups__name__in=STAFF_GROUPS)
        .distinct()
        .count()
    )

    # “Staff” = superusers o users con groups staff
    total_staff = (
        User.objects.filter(is_superuser=True).count()
        +
        User.objects.filter(groups__name__in=STAFF_GROUPS).distinct().count()
    )

    return render(request, "owner/dashboard.html", {
        "billing": billing,
        "total_users": total_users,
        "total_active": total_active,
        "total_customers": total_customers,
        "total_staff": total_staff,
        "can_manage": can_manage,
    })


@staff_required
def users(request):
    """
    Clientes: usuarios que NO son staff y NO son superuser.
    """
    can_manage = _is_admin_general(request.user)

    qs = (
        User.objects
        .select_related("profile")
        .filter(is_superuser=False)
        .exclude(groups__name__in=STAFF_GROUPS)
        .distinct()
        .order_by("username")
    )

    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Solo Admin General puede cambiar planes/estado.")
            return redirect("owner_panel:users")

        user_id = request.POST.get("user_id")
        action = request.POST.get("action") or ""

        u = User.objects.filter(id=user_id).first()
        if not u:
            messages.error(request, "Usuario no existe.")
            return redirect("owner_panel:users")

        _get_profile(u)
        sub = _get_or_create_active_subscription(u)

        if action == "toggle_active":
            u.is_active = not u.is_active
            u.save(update_fields=["is_active"])
            messages.success(request, f"Usuario {'activado' if u.is_active else 'suspendido'} ✅")
            return redirect("owner_panel:users")

        if action == "set_plan":
            code = (request.POST.get("plan") or "").strip().lower()
            plan_obj = _get_plan_by_code(code)
            if not plan_obj:
                messages.error(request, "Plan inválido (free/plus/pro) o no existe en la BD.")
                return redirect("owner_panel:users")

            sub.plan = plan_obj
            sub.status = UserSubscription.STATUS_ACTIVE
            sub.ends_at = None  # cambio manual => sin vencimiento
            sub.save(update_fields=["plan", "status", "ends_at"])
            messages.success(request, f"Plan actualizado a {plan_obj.code.upper()} ✅")
            return redirect("owner_panel:users")

        # Mantengo tus actions, pero las implemento usando Plan + ends_at (sin campos comped_pro/comped_until)
        if action == "give_comped_pro":
            d = _parse_date_yyyy_mm_dd(request.POST.get("comped_until"))
            pro = _get_plan_by_code(Plan.CODE_PRO)
            if not pro:
                messages.error(request, "No existe Plan PRO. Ejecuta seed_plans.")
                return redirect("owner_panel:users")

            sub.plan = pro
            sub.status = UserSubscription.STATUS_ACTIVE
            sub.ends_at = _end_of_day_aware(d) if d else None
            sub.save(update_fields=["plan", "status", "ends_at"])
            messages.success(request, "Pro gratis aplicado ✅")
            return redirect("owner_panel:users")

        if action == "remove_comped":
            free = _get_plan_by_code(Plan.CODE_FREE) or Plan.objects.order_by("id").first()
            sub.plan = free
            sub.status = UserSubscription.STATUS_ACTIVE
            sub.ends_at = None
            sub.save(update_fields=["plan", "status", "ends_at"])
            messages.success(request, "Pro gratis removido ✅")
            return redirect("owner_panel:users")

        messages.error(request, "Acción no válida.")
        return redirect("owner_panel:users")

    rows = []
    for u in qs:
        sub = _get_or_create_active_subscription(u)
        prof = _get_profile(u)
        rows.append({
            "u": u,
            "sub": sub,
            "telegram_linked": bool(prof.telegram_user_id),
        })

    return render(request, "owner/users.html", {"rows": rows, "can_manage": can_manage})


@staff_required
def staff(request):
    """
    Staff:
    - superusers
    - users con groups staff (admin_general/finance/support)
    Crear/Editar/Eliminar: SOLO admin_general (o superuser)
    """
    can_manage = _is_admin_general(request.user)

    def _parse_roles():
        roles = request.POST.getlist("roles") or []
        return [r for r in roles if r in STAFF_GROUPS]

    if request.method == "POST":
        action = request.POST.get("action") or ""

        if action in {"create_staff", "update_staff", "delete_staff"} and not can_manage:
            messages.error(request, "Solo Admin General puede crear/editar/eliminar Staff.")
            return redirect("owner_panel:staff")

        # ---------------- CREATE ----------------
        if action == "create_staff":
            username = (request.POST.get("username") or "").strip()
            email = (request.POST.get("email") or "").strip()
            password1 = request.POST.get("password1") or ""
            password2 = request.POST.get("password2") or ""
            is_active = request.POST.get("is_active") == "1"
            roles = _parse_roles()

            if not username:
                messages.error(request, "Username es obligatorio.")
                return redirect("owner_panel:staff")

            if not roles:
                messages.error(request, "Debes seleccionar al menos 1 rol (Finanzas/Soporte/Admin General).")
                return redirect("owner_panel:staff")

            if password1 != password2 or not password1:
                messages.error(request, "Las contraseñas no coinciden o están vacías.")
                return redirect("owner_panel:staff")

            if User.objects.filter(username=username).exists():
                messages.error(request, "Ya existe un usuario con ese username.")
                return redirect("owner_panel:staff")

            if email and User.objects.filter(email=email).exists():
                messages.error(request, "Ya existe un usuario con ese email.")
                return redirect("owner_panel:staff")

            u = User.objects.create(
                username=username,
                email=email,
                is_active=is_active,
                password=make_password(password1),
            )
            _get_profile(u)

            groups = _ensure_groups(roles)
            u.groups.set(groups)
            u.save()

            messages.success(request, "Staff creado ✅")
            return redirect("owner_panel:staff")

        # ---------------- UPDATE ----------------
        if action == "update_staff":
            user_id = request.POST.get("user_id")
            if not user_id:
                messages.error(request, "Falta user_id.")
                return redirect("owner_panel:staff")

            u = User.objects.filter(id=user_id).first()
            if not u:
                messages.error(request, "Usuario no existe.")
                return redirect("owner_panel:staff")

            _get_profile(u)

            if u.is_superuser and not request.user.is_superuser:
                messages.error(request, "Solo un superuser puede modificar a otro superuser.")
                return redirect("owner_panel:staff")

            username = (request.POST.get("username") or "").strip()
            email = (request.POST.get("email") or "").strip()
            password1 = request.POST.get("password1") or ""
            password2 = request.POST.get("password2") or ""
            is_active = request.POST.get("is_active") == "1"
            roles = _parse_roles()

            if not username:
                messages.error(request, "Username es obligatorio.")
                return redirect("owner_panel:staff")

            if User.objects.filter(username=username).exclude(id=u.id).exists():
                messages.error(request, "Ese username ya está en uso.")
                return redirect("owner_panel:staff")

            if email and User.objects.filter(email=email).exclude(id=u.id).exists():
                messages.error(request, "Ese email ya está en uso.")
                return redirect("owner_panel:staff")

            if not u.is_superuser and not roles:
                messages.error(request, "Debes dejar al menos 1 rol (Finanzas/Soporte/Admin General).")
                return redirect("owner_panel:staff")

            u.username = username
            u.email = email
            u.is_active = is_active

            if password1 or password2:
                if password1 != password2 or not password1:
                    messages.error(request, "Contraseñas no coinciden o vacías.")
                    return redirect("owner_panel:staff")
                u.password = make_password(password1)

            u.save()

            if not u.is_superuser:
                groups = _ensure_groups(roles)
                u.groups.set(groups)

            messages.success(request, "Staff actualizado ✅")
            return redirect("owner_panel:staff")

        # ---------------- DELETE (ROBUSTO) ----------------
        if action == "delete_staff":
            user_id = request.POST.get("user_id")
            if not user_id:
                messages.error(request, "Falta user_id.")
                return redirect("owner_panel:staff")

            u = User.objects.filter(id=user_id).first()
            if not u:
                messages.error(request, "Usuario no existe (quizás ya fue eliminado).")
                return redirect("owner_panel:staff")

            if u.id == request.user.id:
                messages.error(request, "No puedes eliminar tu propio usuario.")
                return redirect("owner_panel:staff")

            if u.is_superuser:
                messages.error(request, "No puedes eliminar un superuser desde aquí.")
                return redirect("owner_panel:staff")

            try:
                with transaction.atomic():
                    deleted_count, _ = User.objects.filter(id=u.id).delete()

                if deleted_count > 0:
                    messages.success(request, "Staff eliminado ✅")
                else:
                    messages.warning(request, "No se eliminó nada (deleted_count=0). Revisa el user_id del POST.")
                return redirect("owner_panel:staff")

            except ProtectedError:
                messages.error(
                    request,
                    "No se puede eliminar porque tiene registros asociados (PROTECT). "
                    "Primero elimina/reasigna lo relacionado o cambia on_delete."
                )
                return redirect("owner_panel:staff")

            except Exception as e:
                messages.error(request, f"Error eliminando: {e}")
                return redirect("owner_panel:staff")

        messages.error(request, "Acción no válida.")
        return redirect("owner_panel:staff")

    # GET: lista staff (superusers + group staff)
    superusers = User.objects.select_related("profile").filter(is_superuser=True).order_by("username")
    staff_by_group = (
        User.objects
        .select_related("profile")
        .filter(groups__name__in=STAFF_GROUPS)
        .distinct()
        .order_by("username")
    )

    all_staff = _dedupe_users(list(superusers) + list(staff_by_group))

    rows = []
    for u in all_staff:
        prof = _get_profile(u)
        rows.append({
            "user": u,
            "profile": prof,
            "roles": _roles_for_user(u),
            "telegram_linked": bool(prof.telegram_user_id),
        })

    return render(request, "owner/staff.html", {
        "rows": rows,
        "can_manage": can_manage,
        "ROLE_ADMIN": ROLE_ADMIN,
        "ROLE_FINANCE": ROLE_FINANCE,
        "ROLE_SUPPORT": ROLE_SUPPORT,
    })


@require_POST
def owner_logout(request):
    logout(request)
    return redirect("accounts:login")