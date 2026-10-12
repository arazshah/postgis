from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import site_user_required
from databases.models import Plan

from . import services
from .forms import NewTicketForm, ReplyForm
from .models import Ticket, TicketMessage


@site_user_required
def ticket_list(request):
    tickets = request.user.tickets.all()
    return render(request, "support/list.html", {"tickets": tickets, "can_open": services.can_open(request.user)})


@site_user_required
def new(request):
    initial = {}
    plan = Plan.objects.filter(slug=request.GET.get("plan", ""), is_public=True).first()
    if plan:
        initial = {"category": Ticket.Category.SALES, "plan": plan, "subject": f"درخواست خرید پلن {plan.name}"}
    if request.GET.get("db", "").isdigit():
        initial["database"] = request.GET["db"]
        initial.setdefault("category", Ticket.Category.DATABASE)
    form = NewTicketForm(request.user, request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            t = services.open_ticket(request.user, subject=d["subject"], category=d["category"], body=d["body"],
                                     database=d.get("database"), plan=d.get("plan"),
                                     attachment=d.get("attachment"))
        except services.SupportError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"تیکت {t.number} ثبت شد. پاسخ را همین‌جا می‌بینید و پیامک هم می‌گیرید.")
            return redirect("support:detail", number=t.number)
    return render(request, "support/new.html", {"form": form, "blocked": services.can_open(request.user)})


@site_user_required
def detail(request, number):
    t = get_object_or_404(Ticket.objects.select_related("database", "plan"), number=number, user=request.user)
    form = ReplyForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.user_reply(t, request.user, form.cleaned_data["body"], form.cleaned_data.get("attachment"))
        except services.SupportError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "پیام شما ثبت شد.")
        return redirect("support:detail", number=t.number)
    return render(request, "support/detail.html", {"t": t, "msgs": t.messages.select_related("author"),
                                                   "form": form})


@site_user_required
@require_POST
def close(request, number):
    t = get_object_or_404(Ticket, number=number, user=request.user)
    services.close(t)
    messages.info(request, "تیکت بسته شد.")
    return redirect("support:detail", number=t.number)


@login_required
def attachment(request, pk):
    m = get_object_or_404(TicketMessage.objects.select_related("ticket"), pk=pk)
    if not m.attachment or not (request.user.is_staff or m.ticket.user_id == request.user.pk):
        raise Http404
    return FileResponse(m.attachment.open("rb"), as_attachment=True, filename=m.attachment_name)
