# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import ValidationError


class VehicleRentalExtraService(models.Model):
    _inherit = "vehicle.rental.extra.service"

    maintenance_request_id = fields.Many2one(
        comodel_name="maintenance.request",
        string="Informe Técnico (Mantenimiento)",
        index=True,
        ondelete="set null",
    )

    def write(self, vals):
        protected = {
            'extra_date', 'product_id', 'description', 'product_qty', 'amount',
            'vehicle_rental_line_id',
        }
        if protected.intersection(vals) and not self.env.context.get('skip_tr_charge_sync'):
            technical_extras = self.filtered(
                lambda extra: extra.maintenance_request_id
                and extra.maintenance_request_id.technical_charge_last_sent_at
            )
            if technical_extras:
                raise ValidationError(_(
                    "Los Extras Operaciones originados por un informe técnico no se modifican directamente. "
                    "Cambia el monto en el mantenimiento y usa 'Enviar a facturación'."
                ))
        return super().write(vals)

    def unlink(self):
        technical_extras = self.filtered(
            lambda extra: extra.maintenance_request_id
            and extra.maintenance_request_id.technical_charge_last_sent_at
        )
        if technical_extras:
            raise ValidationError(_(
                "No se puede eliminar un Extra Operaciones que ya fue enviado desde un informe técnico."
            ))
        return super().unlink()


class VehicleRentalLine(models.Model):
    _inherit = 'vehicle.rental.line'

    def write(self, vals):
        if 'service_currency_id' in vals and not self.env.context.get('skip_tr_charge_sync'):
            new_currency_id = vals.get('service_currency_id') or False
            for line in self:
                if line.service_currency_id.id == new_currency_id:
                    continue
                sent_technical_extras = line.extra_service_ids.filtered(
                    lambda extra: extra.maintenance_request_id
                    and extra.maintenance_request_id.technical_charge_last_sent_at
                )
                if sent_technical_extras:
                    raise ValidationError(_(
                        "No se puede cambiar la moneda de Extra Operaciones porque la línea contiene "
                        "un cargo técnico ya enviado a facturación. Realiza el cambio desde el mantenimiento "
                        "y vuelve a usar 'Enviar a facturación' si aún no existe una factura activa."
                    ))
        return super().write(vals)
