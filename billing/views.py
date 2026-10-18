import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
def pay_gateway(request, number):
    inv = _user_invoice(request, number)
    request_host = urlsplit(f"//{request.get_host()}").hostname
    canonical_host = urlsplit(settings.CANONICAL_URL).hostname
    if request_host and canonical_host and request_host.lower() != canonical_host.lower():
        canonical_invoice = f"{settings.CANONICAL_URL.rstrip('/')}{reverse('billing:invoice', args=[inv.number])}"
        return redirect(canonical_invoice)
    try:
        url = services.start_gateway(inv, request)
    except services.BillingError as exc:
        messages.error(request, str(exc))
        return redirect("billing:invoice", number=inv.number)
    return redirect(url)


def callback(request, number):
    """
    برگشت خریدار از درگاه. نتیجه فقط با verify سمت سرور تعیین می‌شود؛
    پارامترهای برگشتی فقط برای پیدا کردن شناسه پرداخت استفاده می‌شوند.
    """
    inv = get_object_or_404(Invoice, number=number)
    token = request.GET.get("Authority") or request.GET.get("trackId")
    if inv.method == Invoice.Method.GATEWAY and token:
        inv = services.verify_gateway(inv, token)
    if not request.user.is_authenticated or inv.user_id != request.user.pk:
        # نشست کاربر بعد از برگشت از درگاه گاهی از دست می‌رود؛ پرداخت همین حالا تأیید شده است
        return render(request, "billing/callback_result.html", {"inv": inv, "Status": Invoice.Status})
    if inv.status == Invoice.Status.PAID:
        messages.success(request, "پرداخت شما تأیید شد و پلن فعال شد.")
    elif inv.status == Invoice.Status.PENDING:
        messages.error(request, "پرداخت انجام نشد یا لغو شد. اگر مبلغی از حسابتان کم شده، حداکثر ظرف ۷۲ ساعت "
                                "خودکار برمی‌گردد. می‌توانید دوباره پرداخت کنید.")
    return redirect("billing:invoice", number=inv.number)


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
