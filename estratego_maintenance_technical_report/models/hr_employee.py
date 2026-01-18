# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    signature_html = fields.Html(
        string="Firma del empleado",
        help="Firma/plantilla HTML que representa la firma del empleado.",
        sanitize=False,
    )
