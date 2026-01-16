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
    "name": "Maintenance Customize",
    "version": "17.0.1.0.0",
    "category": "maintenance",
    "summary": "Customized fields for Maintenance.",
    "author": "Estratego Consulting SAC",
    "license": "LGPL-3",
    "depends": ["base","maintenance", "hr"],
    "data": [
        "views/maintenance_request_views.xml",
    ],
    "installable": True,
    "application": False,
}
