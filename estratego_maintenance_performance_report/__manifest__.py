# -*- coding: utf-8 -*-
{
    "name": "Reporte de Rendimiento por Mantenimiento",
    "version": "17.0.1.0.1",
    "category": "Rental",
    "summary": "Rentabilidad de mantenimientos, cargos técnicos, costos e impuestos",
    "author": "Estratego Consulting SAC",
    "license": "LGPL-3",
    "depends": [
        "estratego_maintenance_technical_report",
        "estratego_fleet_vehicle_rental",
        "stock_account",
        "purchase",
        "account",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/maintenance_performance_report_views.xml",
    ],
    "installable": True,
    "application": False,
}
