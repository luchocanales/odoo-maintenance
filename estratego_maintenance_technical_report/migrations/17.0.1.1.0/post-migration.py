# -*- coding: utf-8 -*-
"""Adopta como enviados los cargos técnicos del flujo automático anterior.

También intenta reconstruir la línea de factura del cargo técnico usando su
identificador más estable: vehículo + N° de informe técnico. Esto cubre casos
históricos donde el monto/``extra_date`` del Extra fue modificado después de una
factura ya creada por la sincronización automática antigua.
"""
from odoo import api, SUPERUSER_ID


def _expected_invoice_line_name(request):
    vehicle = request.fleet_vehicle_id
    vehicle_label = "%s/%s/%s" % (
        vehicle.model_id.brand_id.name,
        vehicle.model_id.name,
        vehicle.license_plate,
    )
    return "%s (%s)" % (vehicle_label, (request.technical_report_number or '').strip())


def _backfill_technical_invoice_line(env, extra, request):
    if extra._get_active_invoice_lines():
        return
    if not request.order_id or not request.fleet_vehicle_id or not request.technical_report_number:
        return

    lines = env['account.move.line'].sudo().search([
        ('rental_extra_service_id', '=', False),
        ('move_id.invoice_origin', '=', request.order_id.name),
        ('move_id.rent_charge_type', '=', 'charge'),
        ('move_id.move_type', 'in', ('out_invoice', 'out_receipt')),
        ('product_id', '=', extra.product_id.id),
        ('name', '=', _expected_invoice_line_name(request)),
    ], order='id')
    if not lines:
        return

    active = lines.filtered(lambda line: line.move_id.state != 'cancel')
    candidate = active[:1] or lines[:1]
    if candidate:
        candidate.with_context(check_move_validity=False, tracking_disable=True).write({
            'rental_extra_service_id': extra.id,
        })
        if extra.legacy_invoice_move_id:
            extra.with_context(tracking_disable=True).write({
                'legacy_invoice_move_id': False,
            })


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Extra = env['vehicle.rental.extra.service'].sudo()

    extras = Extra.search([
        ('maintenance_request_id', '!=', False),
    ])
    for extra in extras:
        request = extra.maintenance_request_id
        _backfill_technical_invoice_line(env, extra, request)

        currency = request.technical_charge_currency_id or request.company_id.currency_id
        amount = request.technical_charge_amount or 0.0

        # El flujo anterior llegaba a crear Extras técnicos de importe 0 al crear
        # el mantenimiento. Esos registros NO deben considerarse un envío real.
        if not currency or currency.is_zero(amount):
            continue
        if request.technical_charge_last_sent_at:
            continue

        request.with_context(tracking_disable=True).write({
            'technical_charge_last_sent_amount': amount,
            'technical_charge_last_sent_currency_id': currency.id,
            'technical_charge_last_sent_at': extra.write_date or extra.create_date,
            'technical_charge_last_sent_user_id': False,
        })
