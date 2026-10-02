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
    maintenance_additional_concept_id = fields.Many2one(
        comodel_name="maintenance.additional.concept",
        string="Concepto adicional de mantenimiento",
        index=True,
        copy=False,
        ondelete="restrict",
    )

    _sql_constraints = [
        (
            "maintenance_additional_concept_extra_unique",
            "unique(maintenance_additional_concept_id)",
            "Un concepto adicional de mantenimiento solo puede generar un Extra Operaciones.",
        ),
    ]

    def _is_protected_maintenance_extra(self):
        self.ensure_one()
        technical_sent = bool(
            self.maintenance_request_id
            and self.maintenance_request_id.technical_charge_last_sent_at
        )
        concept_sent = bool(
            self.maintenance_additional_concept_id
            and self.maintenance_additional_concept_id.last_sent_at
        )
        return technical_sent or concept_sent

    def write(self, vals):
        protected = {
            'extra_date', 'product_id', 'description', 'product_qty', 'amount',
            'vehicle_rental_line_id',
        }
        if protected.intersection(vals) and not self.env.context.get('skip_tr_charge_sync'):
            protected_extras = self.filtered(lambda extra: extra._is_protected_maintenance_extra())
            if protected_extras:
                raise ValidationError(_(
                    "Los Extras Operaciones originados desde mantenimiento no se modifican directamente. "
                    "Realiza el cambio en el mantenimiento y usa 'Enviar a facturación'."
                ))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('skip_tr_charge_sync'):
            protected_extras = self.filtered(lambda extra: extra._is_protected_maintenance_extra())
            if protected_extras:
                raise ValidationError(_(
                    "No se puede eliminar un Extra Operaciones que ya fue enviado desde mantenimiento."
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
                sent_maintenance_extras = line.extra_service_ids.filtered(
                    lambda extra: extra._is_protected_maintenance_extra()
                )
                if sent_maintenance_extras:
                    raise ValidationError(_(
                        "No se puede cambiar la moneda de Extra Operaciones porque la línea contiene "
                        "cargos enviados desde mantenimiento. Realiza cualquier corrección desde el "
                        "mantenimiento y vuelve a usar 'Enviar a facturación' si todavía no existe una factura activa."
                    ))
        return super().write(vals)
