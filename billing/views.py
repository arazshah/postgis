import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.decorators import site_user_required
from core.models import SiteSettings
from databases.models import Plan, UserDatabase

from . import services
from .forms import ReceiptForm
from .models import Invoice

log = logging.getLogger(__name__)


def _user_invoice(request, number) -> Invoice:
    return get_object_or_404(Invoice.objects.select_related("plan", "database"), number=number, user=request.user)


@site_user_required
def plans(request):
    conf = SiteSettings.get()
    dbs = request.user.databases.exclude(status__in=[UserDatabase.Status.DELETED, UserDatabase.Status.ERROR,
                                                     UserDatabase.Status.PENDING]).select_related("plan")
    return render(request, "billing/plans.html", {
        "plans": services.paid_plans(), "dbs": dbs, "enabled": conf.pay_enabled and services.methods_available(conf),
        "selected_plan": request.GET.get("plan", ""), "selected_db": request.GET.get("db", ""),
    })


@site_user_required
@require_POST
def start(request):
    plan = get_object_or_404(Plan, slug=request.POST.get("plan", ""))
    target = request.POST.get("target", "new")
    db = None
    kind = Invoice.Kind.NEW
    if target != "new":
        db = get_object_or_404(UserDatabase, pk=target if target.isdigit() else 0, owner=request.user)
        kind = Invoice.Kind.UPGRADE
    try:
        inv = services.create_invoice(request.user, kind, plan, db)
    except services.BillingError as exc:
        messages.error(request, str(exc))
        return redirect("billing:plans")
    return redirect("billing:invoice", number=inv.number)


@site_user_required
def invoice(request, number):
    inv = _user_invoice(request, number)
    if inv.method == Invoice.Method.ABAN and inv.status == Invoice.Status.PENDING:
        inv = services.check_aban(inv)
    if inv.is_expired_now:
        inv.status = Invoice.Status.EXPIRED
        inv.save(update_fields=["status"])
    conf = SiteSettings.get()
    return render(request, "billing/invoice.html", {
        "inv": inv, "conf": conf, "methods": services.methods_available(conf),
        "form": ReceiptForm(), "Status": Invoice.Status,
    })


@site_user_required
@require_POST
def pay_aban(request, number):
    inv = _user_invoice(request, number)
    try:
        url = services.start_aban(inv, request)
    except services.BillingError as exc:
        messages.error(request, str(exc))
        return redirect("billing:invoice", number=inv.number)
    return redirect(url)


@csrf_exempt
def callback(request, number):
    """
    دو کاربرد دارد:
    - POST: وب‌هوک آبان (callback_url). به بدنه اعتماد نمی‌کنیم؛ فقط استعلام مستقیم از API.
    - GET: برگشت خریدار به سایت.
    """
    if request.method == "POST":
        inv = Invoice.objects.filter(number=number, method=Invoice.Method.ABAN).first()
        if inv:
            services.check_aban(inv)
        return HttpResponse("ok")
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    inv = get_object_or_404(Invoice, number=number, user=request.user)
    inv = services.check_aban(inv)
    if inv.status == Invoice.Status.PAID:
        messages.success(request, "پرداخت شما تأیید شد و پلن فعال شد.")
    elif inv.status == Invoice.Status.PENDING:
        messages.info(request, "پرداخت هنوز تأیید نشده است. اگر واریز کرده‌اید، چند ثانیه صبر کنید؛ این صفحه خودکار به‌روز می‌شود.")
    elif inv.status == Invoice.Status.REVIEW:
        messages.info(request, "پرداخت دریافت شد و برای بررسی نهایی نزد پشتیبانی است.")
    else:
        messages.error(request, "پرداخت تأیید نشد. اگر مبلغی از حسابتان کم شده، با پشتیبانی تماس بگیرید.")
    return redirect("billing:invoice", number=inv.number)


@csrf_exempt
@require_POST
def aban_webhook(request):
    """
    اعلان آبان: به محتوای آن اعتماد نمی‌کنیم؛ فقط فاکتور را پیدا و وضعیت را مستقیم از API استعلام می‌کنیم.
    """
    try:
        data = json.loads(request.body.decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponse(status=400)
    candidates = []
    if isinstance(data, dict):
        for c in (data, data.get("data") or {}, data.get("invoice") or {}):
            if isinstance(c, dict):
                candidates += [c.get("order_id"), c.get("id"), c.get("invoice_id")]
    inv = (Invoice.objects.filter(number__in=[c for c in candidates if isinstance(c, str)]).first()
           or Invoice.objects.filter(provider_id__in=[str(c) for c in candidates if c], method=Invoice.Method.ABAN)
           .first())
    if inv:
        services.check_aban(inv)
    return HttpResponse("ok")


@site_user_required
@require_POST
def receipt(request, number):
    inv = _user_invoice(request, number)
    form = ReceiptForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            services.submit_receipt(inv, receipt=form.cleaned_data["receipt"], last4=form.cleaned_data["last4"],
                                    tracking=form.cleaned_data["tracking"], paid_time=form.cleaned_data["paid_time"])
            messages.success(request, "رسید ثبت شد. بعد از بررسی، پلن فعال می‌شود و پیامک می‌گیرید.")
            return redirect("billing:invoice", number=inv.number)
        except services.BillingError as exc:
            messages.error(request, str(exc))
            return redirect("billing:invoice", number=inv.number)
    conf = SiteSettings.get()
    return render(request, "billing/invoice.html", {
        "inv": inv, "conf": conf, "methods": services.methods_available(conf), "form": form,
        "Status": Invoice.Status, "show_manual": True}, status=400)


@site_user_required
@require_POST
def cancel(request, number):
    inv = _user_invoice(request, number)
    if inv.status == Invoice.Status.PENDING:
        services.cancel_invoice(inv)
        inv.refresh_from_db()
        if inv.status == Invoice.Status.CANCELLED:
            messages.info(request, "فاکتور لغو شد.")
        else:
            messages.info(request, f"فاکتور لغو نشد؛ وضعیت فعلی: {inv.get_status_display()}")
    return redirect("billing:invoices")


@site_user_required
def invoices(request):
    return render(request, "billing/invoices.html", {
        "invoices": request.user.invoices.select_related("plan", "database")[:100]})


@login_required
def receipt_file(request, number):
    inv = get_object_or_404(Invoice, number=number)
    if not (request.user.is_staff or inv.user_id == request.user.pk) or not inv.receipt:
        raise Http404
    return FileResponse(inv.receipt.open("rb"))
