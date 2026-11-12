"""نمای «تیم و کاربران»."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from databases.crypto import generate_password
from databases.provisioner import ProvisionError
from kernel import workspace

# ---------------------------------------------------------------------- تیم و کاربران پایگاه داده
SESSION_ROLE_PW = "gp_role_pw_{}"


@site_user_required
@require_http_methods(["GET", "POST"])
def team_page(request, pk):
    from databases import team
    from databases.models import DbRole, Member

    db = workspace.get(request, pk)
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "invite":
                m = team.invite(db, request.user, request.POST.get("phone", ""), request.POST.get("role", "viewer"))
                messages.success(request, f"{m.phone} با نقش {m.get_role_display()} اضافه شد."
                                 + ("" if m.user_id else " وقتی با همین شماره وارد سایت شود، پایگاه داده را می‌بیند."))
            elif action == "remove":
                team.remove_member(db, request.user, get_object_or_404(Member, pk=request.POST.get("id"), database=db))
                messages.success(request, "عضو حذف شد.")
            elif action == "role_create":
                pw = generate_password()
                role = team.create_role(db, request.user, request.POST.get("suffix", ""),
                                        request.POST.get("access", "read"), pw, request.POST.get("note", ""))
                request.session[SESSION_ROLE_PW.format(db.pk)] = {"name": role.name, "password": pw}
            elif action == "role_password":
                role = get_object_or_404(DbRole, pk=request.POST.get("id"), database=db)
                pw = generate_password()
                team.reset_role_password(db, request.user, role, pw)
                request.session[SESSION_ROLE_PW.format(db.pk)] = {"name": role.name, "password": pw}
            elif action == "role_drop":
                team.drop_role(db, request.user, get_object_or_404(DbRole, pk=request.POST.get("id"), database=db))
                messages.success(request, "کاربر حذف شد و اتصال‌هایش قطع شد.")
        except team.TeamError as exc:
            messages.error(request, str(exc))
        except ProvisionError as exc:
            messages.error(request, f"عملیات روی سرور ناموفق بود: {exc}")
        return redirect("databases:team", pk=db.pk)
    return render(request, "databases/team.html", {
        "db": db, "members": db.members.select_related("user"), "roles": db.db_roles.all(),
        "new_pw": request.session.pop(SESSION_ROLE_PW.format(db.pk), None),
        "role_prefix": team.role_name_for(db, ""),
    })
