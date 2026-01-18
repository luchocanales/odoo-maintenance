# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) estratego Consulting SAC (<https://estratego.pe>).
#
#    For Module Support : info@estratego.pe
#
##############################################################################
{
    "name": "Informe Técnico de Mantenimiento",
    "version": "17.0.1.0.0",
    "category": "maintenance",
    "summary": "Formulario de informe técnico y reporte PDF",
    "author": "Estratego Consulting SAC",
    "license": "LGPL-3",
    "depends": [
        "maintenance",
        "hr",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/hr_employee_views.xml",
        "views/maintenance_request_views.xml",
        "report/technical_report_templates.xml",
        "report/technical_report_action.xml",
    ],
    "installable": True,
    "application": False,
}
