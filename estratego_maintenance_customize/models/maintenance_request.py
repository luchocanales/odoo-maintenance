# -*- coding: utf-8 -*-
from odoo import fields, models


class MaintenanceRequest(models.Model):
    _inherit = "maintenance.request"

    responsible_employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Responsable",
        help="Empleado responsable de atender la solicitud.",
    )
    workshop_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Taller",
        help="Proveedor / taller asignado para la atención de la solicitud.",
        domain=[("company_type", "=", "company"), ("parent_id", "=", False)],
    )
    city_id = fields.Many2one(
        comodel_name="res.city",
        string="Lugar",
        help="Ciudad donde se atenderá la solicitud.",
    )
    delivery_guide = fields.Char(
        string="Guía de Remisión",
        help="Número de guía de remisión asociada a la solicitud.",
    )
