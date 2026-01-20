# -*- coding: utf-8 -*-
from odoo import fields, models


class VehicleRentalExtraService(models.Model):
    _inherit = "vehicle.rental.extra.service"

    maintenance_request_id = fields.Many2one(
        comodel_name="maintenance.request",
        string="Informe Técnico (Mantenimiento)",
        index=True,
        ondelete="set null",
    )
