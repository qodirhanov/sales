"""Write API on the new models: submit a price and confirm one, through the verification rules.

Request fields keep the names and unit codes the add-price form already uses ("location" is a Place id,
units are kg/g/l/ml/piece), plus optional lat/lng of the reporter. Responses add what the old API lacked:
the report's status, points and the "what others reported" context shown after submitting (rule 6).
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Place, Product
from apps.reports.models import PriceReport
from apps.reports.validators import validate_http_url
from apps.verification import services as verification
from apps.verification.errors import AlreadyConfirmed, RateLimited, ReportClosed, SelfConfirmation

from .selectors import UNIT_IN
from .throttles import ConfirmThrottle, PriceCreateThrottle


class ReportInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    location = serializers.PrimaryKeyRelatedField(queryset=Place.objects.filter(is_active=True))
    price = serializers.IntegerField(min_value=1, max_value=10 ** 10)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=0, default=1)
    unit = serializers.ChoiceField(choices=sorted(UNIT_IN))
    is_promo = serializers.BooleanField(default=False)
    old_price = serializers.IntegerField(min_value=1, max_value=10 ** 10, required=False, allow_null=True)
    source_url = serializers.URLField(max_length=500, required=False, allow_blank=True,
                                      validators=[validate_http_url])
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True,
                                   min_value=-90, max_value=90)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True,
                                   min_value=-180, max_value=180)

    def validate(self, data):
        if data["quantity"] <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
        if (data.get("lat") is None) != (data.get("lng") is None):
            raise serializers.ValidationError({"lat": "lat and lng must be sent together."})
        old = data.get("old_price")
        if old is not None and old <= data["price"]:
            raise serializers.ValidationError({"old_price": "Old price must be higher than the price."})
        if not data["is_promo"]:
            data["old_price"] = None  # an old price only means something for a promo
        data["unit"] = UNIT_IN[data["unit"]]
        return data


def _report_payload(result):
    report = result.report
    ctx = result.context
    return {
        "id": report.pk, "status": report.status, "is_far": report.is_far, "distance_m": report.distance_m,
        "points_awarded": report.points_awarded, "normalized_price": report.normalized_price,
        "context": ctx,
    }


class ReportCreateView(APIView):
    """POST: any logged-in user. Rules: nearby (500 m), anomaly check, one report per user/place/product per 6 h."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [PriceCreateThrottle]
    throttle_scope = "price_create"

    def post(self, request):
        s = ReportInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            result = verification.submit_report(
                user=request.user, product=d["product"], place=d["location"], price=d["price"],
                unit=d["unit"], quantity=d["quantity"], reporter_lat=d.get("lat"), reporter_lng=d.get("lng"),
                is_promo=d["is_promo"], old_price=d.get("old_price"), source_url=d.get("source_url", ""))
        except RateLimited as e:
            return Response({"detail": str(e), "code": e.code,
                             "retry_after_seconds": int(e.retry_after.total_seconds())},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict if hasattr(e, "error_dict") else {"detail": e.messages})
        return Response(_report_payload(result), status=status.HTTP_201_CREATED)


class ReportConfirmView(APIView):
    """POST /prices/<id>/confirm/: vouch for a price. 201 new, 200 already confirmed by you, 403 own, 409 closed."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ConfirmThrottle]
    throttle_scope = "price_confirm"

    def post(self, request, pk):
        report = get_object_or_404(PriceReport, pk=pk)
        try:
            result = verification.confirm_report(report, request.user)
        except AlreadyConfirmed:
            return Response(self._body(report), status=status.HTTP_200_OK)
        except SelfConfirmation as e:
            return Response({"detail": str(e), "code": e.code}, status=status.HTTP_403_FORBIDDEN)
        except ReportClosed as e:
            return Response({"detail": str(e), "code": e.code}, status=status.HTTP_409_CONFLICT)
        body = self._body(result.report)
        body["became_confirmed"] = result.became_confirmed
        return Response(body, status=status.HTTP_201_CREATED)

    @staticmethod
    def _body(report):
        report.refresh_from_db()
        return {"id": report.pk, "status": report.status, "confirmations": report.confirmations.count(),
                "is_flagged": report.status == PriceReport.Status.FLAGGED}
