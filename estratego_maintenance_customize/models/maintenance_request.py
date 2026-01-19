# -*- coding: utf-8 -*-
from odoo import fields, models


class MaintenanceRequest(models.Model):
    _inherit = "maintenance.request"

    responsible_employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Responsable",
        tracking=True,
        help="Empleado responsable de atender la solicitud.",
    )
    supervisor_employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Supervisor",
        tracking=True,
        help="Empleado supervisor del mantenimiento.",
    )    
    workshop_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Taller",
        help="Proveedor / taller asignado para la atención de la solicitud.",
        tracking=True,
        domain=[("company_type", "=", "company"), ("parent_id", "=", False)],
    )
    city_id = fields.Many2one(
        comodel_name="res.city",
        string="Lugar",
        tracking=True,
        help="Ciudad donde se atenderá la solicitud.",
    )
    delivery_guide = fields.Char(
        string="Guía de Remisión",
        tracking=True,
        help="Número de guía de remisión asociada a la solicitud.",
    )
