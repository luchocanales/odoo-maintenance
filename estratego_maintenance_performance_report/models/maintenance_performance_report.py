# -*- coding: utf-8 -*-
from odoo import fields, models


class MaintenancePerformanceReport(models.Model):
    _name = "report.maintenance.performance"
    _description = "Reporte de rendimiento por Mantenimiento"
    _auto = False
    _rec_name = "technical_report_number"
    _order = "request_date desc, id desc"

    maintenance_request_id = fields.Many2one(
        "maintenance.request",
        string="Mantenimiento",
        readonly=True,
    )
    company_id = fields.Many2one("res.company", string="Compañía", readonly=True)
    company_currency_id = fields.Many2one(
        "res.currency",
        string="Moneda Compañía",
        readonly=True,
    )
    vehicle_id = fields.Many2one("fleet.vehicle", string="Vehículo", readonly=True)
    license_plate = fields.Char(string="Placa del Vehículo", readonly=True)
    request_date = fields.Date(string="Fecha de Solicitud de Mantenimiento", readonly=True)
    technical_report_number = fields.Char(string="Informe Técnico", readonly=True)
    order_id = fields.Many2one("sale.order", string="Número de Orden Renting asociado", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", readonly=True)

    billing_status = fields.Selection(
        [
            ("not_submitted", "No presentado"),
            ("submitted", "Presentado"),
            ("invoiced", "Facturado"),
        ],
        string="Estado",
        readonly=True,
    )
    billing_traceability = fields.Selection(
        [
            ("none", "Sin trazabilidad de factura"),
            ("exact", "Exacta por línea"),
            ("legacy", "Histórica inferida"),
        ],
        string="Trazabilidad de Facturación",
        readonly=True,
    )
    invoice_id = fields.Many2one("account.move", string="Factura", readonly=True)
    billed_currency_id = fields.Many2one(
        "res.currency",
        string="Moneda facturada",
        readonly=True,
    )
    maintenance_cost_company = fields.Monetary(
        string="Costo del mantenimiento",
        currency_field="company_currency_id",
        readonly=True,
        help="Costo bruto de partes/insumos y servicios, incluyendo impuestos, expresado en moneda compañía.",
    )
    billed_amount_original = fields.Monetary(
        string="Monto facturado (moneda original)",
        currency_field="billed_currency_id",
        readonly=True,
        help="Venta neta de notas de crédito, con impuestos, en la moneda de la factura.",
    )
    billed_amount_company = fields.Monetary(
        string="Monto facturado (moneda compañía)",
        currency_field="company_currency_id",
        readonly=True,
        help="Venta neta de notas de crédito, con impuestos, convertida a moneda compañía con la tasa contable de cada documento.",
    )
    gross_profit = fields.Monetary(
        string="Utilidad bruta",
        currency_field="company_currency_id",
        readonly=True,
        help="Monto facturado en moneda compañía menos costo bruto del mantenimiento.",
    )
    technical_charge_last_sent_at = fields.Datetime(
        string="Fecha de presentación",
        readonly=True,
    )
    cost_tax_estimated = fields.Boolean(
        string="Costo con impuesto estimado",
        readonly=True,
        help=(
            "Indica que al menos un costo manual tuvo que usar impuestos actuales del producto "
            "o una conversión de moneda de respaldo, en vez de un documento proveedor contabilizado."
        ),
    )

    @property
    def _table_query(self):
        # Una fila por maintenance.request. Los costos y ventas se calculan desde
        # documentos operativos/contables vigentes; no se almacenan snapshots.
        return r"""
            WITH RECURSIVE
            svl_tree(part_id, svl_id, value) AS (
                SELECT
                    mp.id AS part_id,
                    svl.id AS svl_id,
                    svl.value AS value
                FROM maintenance_part mp
                JOIN stock_move sm
                    ON sm.maintenance_part_id = mp.id
                   AND sm.state = 'done'
                JOIN stock_valuation_layer svl
                    ON svl.stock_move_id = sm.id

                UNION

                SELECT
                    parent.part_id,
                    child.id,
                    child.value
                FROM svl_tree parent
                JOIN stock_valuation_layer child
                    ON child.stock_valuation_layer_id = parent.svl_id
            ),
            part_net AS (
                SELECT
                    part_id,
                    GREATEST(0.0, -SUM(value)) AS net_cost_company
                FROM svl_tree
                GROUP BY part_id
            ),
            product_purchase_tax_leaf AS (
                -- Impuestos simples de compra del producto.
                SELECT
                    rel.prod_id AS product_tmpl_id,
                    tax.company_id,
                    tax.id AS tax_id,
                    tax.amount_type,
                    tax.amount
                FROM product_supplier_taxes_rel rel
                JOIN account_tax tax ON tax.id = rel.tax_id
                WHERE tax.active
                  AND tax.amount_type <> 'group'

                UNION ALL

                -- Un grupo de impuestos se expande a sus hijos. Odoo no permite
                -- grupos anidados, por lo que un nivel es suficiente.
                SELECT
                    rel.prod_id AS product_tmpl_id,
                    child.company_id,
                    child.id AS tax_id,
                    child.amount_type,
                    child.amount
                FROM product_supplier_taxes_rel rel
                JOIN account_tax parent_tax ON parent_tax.id = rel.tax_id
                JOIN account_tax_filiation_rel filiation
                    ON filiation.parent_tax = parent_tax.id
                JOIN account_tax child ON child.id = filiation.child_tax
                WHERE parent_tax.active
                  AND child.active
                  AND parent_tax.amount_type = 'group'
            ),
            product_purchase_tax_factor AS (
                SELECT
                    product_tmpl_id,
                    company_id,
                    1.0 + SUM(
                        CASE
                            WHEN amount_type = 'percent' THEN amount / 100.0
                            ELSE 0.0
                        END
                    ) AS tax_factor,
                    BOOL_OR(amount_type <> 'percent') AS has_non_percentage_tax
                FROM product_purchase_tax_leaf
                GROUP BY product_tmpl_id, company_id
            ),
            maintenance_currency_rate AS (
                SELECT
                    mr.id AS maintenance_request_id,
                    CASE
                        WHEN mr.currency_id = rc.currency_id THEN 1.0
                        ELSE COALESCE((
                            SELECT r.rate
                            FROM res_currency_rate r
                            WHERE r.currency_id = mr.currency_id
                              AND r.name <= COALESCE(mr.request_date, CURRENT_DATE)
                              AND (r.company_id IS NULL OR r.company_id = mr.company_id)
                            ORDER BY
                                CASE WHEN r.company_id = mr.company_id THEN 0 ELSE 1 END,
                                r.name DESC,
                                r.id DESC
                            LIMIT 1
                        ), 1.0)
                    END AS rate_to_company,
                    CASE
                        WHEN mr.currency_id = rc.currency_id THEN FALSE
                        ELSE NOT EXISTS (
                            SELECT 1
                            FROM res_currency_rate r
                            WHERE r.currency_id = mr.currency_id
                              AND r.name <= COALESCE(mr.request_date, CURRENT_DATE)
                              AND (r.company_id IS NULL OR r.company_id = mr.company_id)
                        )
                    END AS missing_rate
                FROM maintenance_request mr
                JOIN res_company rc ON rc.id = mr.company_id
            ),
            part_cost AS (
                SELECT
                    mp.maintenance_request_id,
                    SUM(
                        COALESCE(pn.net_cost_company, 0.0)
                        * COALESCE(
                            CASE
                                WHEN pol.id IS NOT NULL
                                 AND ABS(COALESCE(pol.price_subtotal, 0.0)) > 0.0000001
                                THEN ABS(pol.price_total / pol.price_subtotal)
                                ELSE NULL
                            END,
                            tax_factor.tax_factor,
                            1.0
                        )
                    ) AS gross_cost_company,
                    BOOL_OR(
                        pol.id IS NULL
                        OR ABS(COALESCE(pol.price_subtotal, 0.0)) <= 0.0000001
                        OR COALESCE(tax_factor.has_non_percentage_tax, FALSE)
                    ) AS tax_estimated
                FROM maintenance_part mp
                JOIN maintenance_request mr ON mr.id = mp.maintenance_request_id
                LEFT JOIN part_net pn ON pn.part_id = mp.id
                LEFT JOIN purchase_order_line pol ON pol.id = mp.purchase_order_line_id
                LEFT JOIN product_product product ON product.id = mp.product_id
                LEFT JOIN product_purchase_tax_factor tax_factor
                    ON tax_factor.product_tmpl_id = product.product_tmpl_id
                   AND tax_factor.company_id = mr.company_id
                GROUP BY mp.maintenance_request_id
            ),
            service_invoice_cost AS (
                SELECT
                    ms.id AS service_id,
                    ms.maintenance_request_id,
                    SUM(
                        aml.balance
                        * COALESCE(
                            CASE
                                WHEN ABS(COALESCE(aml.price_subtotal, 0.0)) > 0.0000001
                                THEN ABS(aml.price_total / aml.price_subtotal)
                                ELSE NULL
                            END,
                            CASE
                                WHEN ABS(COALESCE(am.amount_total, 0.0)) > 0.0000001
                                THEN ABS(am.amount_total_signed / am.amount_total)
                                ELSE 1.0
                            END
                        )
                        * COALESCE(
                            (
                                SELECT SUM((entry.value)::numeric)
                                FROM jsonb_each_text(COALESCE(aml.analytic_distribution, '{}'::jsonb)) entry
                                WHERE fv.analytic_account_id IS NOT NULL
                                  AND fv.analytic_account_id::text = ANY(
                                      string_to_array(replace(entry.key, ' ', ''), ',')
                                  )
                            ),
                            NULLIF(ms.analytic_percentage, 0.0),
                            0.0
                        ) / 100.0
                    ) AS gross_cost_company
                FROM maintenance_service ms
                JOIN maintenance_request mr ON mr.id = ms.maintenance_request_id
                LEFT JOIN fleet_vehicle fv ON fv.id = mr.fleet_vehicle_id
                JOIN account_move_line aml
                    ON aml.purchase_line_id = ms.purchase_order_line_id
                   AND aml.display_type = 'product'
                JOIN account_move am
                    ON am.id = aml.move_id
                   AND am.state = 'posted'
                   AND am.move_type IN ('in_invoice', 'in_refund')
                WHERE ms.purchase_order_line_id IS NOT NULL
                GROUP BY ms.id, ms.maintenance_request_id
            ),
            service_cost AS (
                SELECT
                    ms.maintenance_request_id,
                    SUM(
                        CASE
                            WHEN ms.purchase_order_line_id IS NOT NULL
                                THEN COALESCE(sic.gross_cost_company, 0.0)
                            ELSE
                                COALESCE(ms.service_charge, 0.0)
                                / NULLIF(COALESCE(mcr.rate_to_company, 1.0), 0.0)
                                * COALESCE(tax_factor.tax_factor, 1.0)
                        END
                    ) AS gross_cost_company,
                    BOOL_OR(
                        ms.purchase_order_line_id IS NULL
                        AND (
                            COALESCE(tax_factor.has_non_percentage_tax, FALSE)
                            OR COALESCE(mcr.missing_rate, FALSE)
                            OR tax_factor.tax_factor IS NULL
                        )
                    ) AS tax_estimated
                FROM maintenance_service ms
                JOIN maintenance_request mr ON mr.id = ms.maintenance_request_id
                LEFT JOIN service_invoice_cost sic ON sic.service_id = ms.id
                LEFT JOIN maintenance_currency_rate mcr
                    ON mcr.maintenance_request_id = ms.maintenance_request_id
                LEFT JOIN product_product product ON product.id = ms.product_id
                LEFT JOIN product_purchase_tax_factor tax_factor
                    ON tax_factor.product_tmpl_id = product.product_tmpl_id
                   AND tax_factor.company_id = mr.company_id
                GROUP BY ms.maintenance_request_id
            ),
            total_cost AS (
                SELECT
                    mr.id AS maintenance_request_id,
                    COALESCE(pc.gross_cost_company, 0.0)
                    + COALESCE(sc.gross_cost_company, 0.0) AS gross_cost_company,
                    COALESCE(pc.tax_estimated, FALSE)
                    OR COALESCE(sc.tax_estimated, FALSE) AS tax_estimated
                FROM maintenance_request mr
                LEFT JOIN part_cost pc ON pc.maintenance_request_id = mr.id
                LEFT JOIN service_cost sc ON sc.maintenance_request_id = mr.id
            ),
            technical_extra AS (
                SELECT DISTINCT ON (extra.maintenance_request_id)
                    extra.maintenance_request_id,
                    extra.id AS extra_id,
                    extra.legacy_invoice_move_id
                FROM vehicle_rental_extra_service extra
                WHERE extra.maintenance_request_id IS NOT NULL
                ORDER BY extra.maintenance_request_id, extra.id DESC
            ),
            exact_posted_billing AS (
                SELECT
                    extra.maintenance_request_id,
                    MIN(am.id) FILTER (
                        WHERE am.move_type IN ('out_invoice', 'out_receipt')
                    ) AS invoice_id,
                    CASE
                        WHEN COUNT(DISTINCT am.currency_id) = 1 THEN MIN(am.currency_id)
                        ELSE NULL
                    END AS billed_currency_id,
                    CASE
                        WHEN COUNT(DISTINCT am.currency_id) = 1 THEN
                            SUM(
                                CASE WHEN am.move_type = 'out_refund' THEN -1.0 ELSE 1.0 END
                                * aml.price_total
                            )
                        ELSE NULL
                    END AS billed_amount_original,
                    SUM(
                        CASE WHEN am.move_type = 'out_refund' THEN -1.0 ELSE 1.0 END
                        * aml.price_total
                        * COALESCE(
                            CASE
                                WHEN ABS(COALESCE(aml.price_subtotal, 0.0)) > 0.0000001
                                THEN ABS(aml.balance / aml.price_subtotal)
                                ELSE NULL
                            END,
                            CASE
                                WHEN ABS(COALESCE(am.amount_total, 0.0)) > 0.0000001
                                THEN ABS(am.amount_total_signed / am.amount_total)
                                ELSE 1.0
                            END
                        )
                    ) AS billed_amount_company,
                    BOOL_OR(am.move_type IN ('out_invoice', 'out_receipt')) AS has_posted_invoice
                FROM technical_extra extra
                JOIN account_move_line aml ON aml.rental_extra_service_id = extra.extra_id
                JOIN account_move am
                    ON am.id = aml.move_id
                   AND am.state = 'posted'
                   AND am.move_type IN ('out_invoice', 'out_receipt', 'out_refund')
                GROUP BY extra.maintenance_request_id
            ),
            active_exact_invoice AS (
                SELECT DISTINCT ON (extra.maintenance_request_id)
                    extra.maintenance_request_id,
                    am.id AS invoice_id
                FROM technical_extra extra
                JOIN account_move_line aml ON aml.rental_extra_service_id = extra.extra_id
                JOIN account_move am
                    ON am.id = aml.move_id
                   AND am.state <> 'cancel'
                   AND am.move_type IN ('out_invoice', 'out_receipt')
                ORDER BY extra.maintenance_request_id,
                         CASE WHEN am.state = 'posted' THEN 0 ELSE 1 END,
                         am.id DESC
            )
            SELECT
                mr.id AS id,
                mr.id AS maintenance_request_id,
                mr.company_id,
                rc.currency_id AS company_currency_id,
                mr.fleet_vehicle_id AS vehicle_id,
                fv.license_plate AS license_plate,
                mr.request_date AS request_date,
                mr.technical_report_number AS technical_report_number,
                mr.order_id AS order_id,
                so.partner_id AS partner_id,
                CASE
                    WHEN COALESCE(epb.has_posted_invoice, FALSE) THEN 'invoiced'
                    WHEN legacy.id IS NOT NULL
                     AND legacy.state = 'posted'
                     AND legacy.move_type IN ('out_invoice', 'out_receipt') THEN 'invoiced'
                    WHEN mr.technical_charge_last_sent_at IS NOT NULL THEN 'submitted'
                    ELSE 'not_submitted'
                END AS billing_status,
                CASE
                    WHEN aei.invoice_id IS NOT NULL OR COALESCE(epb.has_posted_invoice, FALSE) THEN 'exact'
                    WHEN legacy.id IS NOT NULL THEN 'legacy'
                    ELSE 'none'
                END AS billing_traceability,
                COALESCE(epb.invoice_id, aei.invoice_id, legacy.id) AS invoice_id,
                CASE
                    WHEN COALESCE(epb.has_posted_invoice, FALSE) THEN epb.billed_currency_id
                    WHEN legacy.id IS NOT NULL
                     AND legacy.state = 'posted'
                     AND legacy.move_type IN ('out_invoice', 'out_receipt') THEN legacy.currency_id
                    ELSE NULL
                END AS billed_currency_id,
                COALESCE(tc.gross_cost_company, 0.0) AS maintenance_cost_company,
                CASE
                    WHEN COALESCE(epb.has_posted_invoice, FALSE) THEN epb.billed_amount_original
                    ELSE NULL
                END AS billed_amount_original,
                CASE
                    WHEN COALESCE(epb.has_posted_invoice, FALSE) THEN epb.billed_amount_company
                    ELSE NULL
                END AS billed_amount_company,
                CASE
                    WHEN COALESCE(epb.has_posted_invoice, FALSE)
                     AND epb.billed_amount_company IS NOT NULL
                    THEN epb.billed_amount_company - COALESCE(tc.gross_cost_company, 0.0)
                    ELSE NULL
                END AS gross_profit,
                mr.technical_charge_last_sent_at,
                COALESCE(tc.tax_estimated, FALSE) AS cost_tax_estimated
            FROM maintenance_request mr
            JOIN res_company rc ON rc.id = mr.company_id
            LEFT JOIN fleet_vehicle fv ON fv.id = mr.fleet_vehicle_id
            LEFT JOIN sale_order so ON so.id = mr.order_id
            LEFT JOIN total_cost tc ON tc.maintenance_request_id = mr.id
            LEFT JOIN technical_extra te ON te.maintenance_request_id = mr.id
            LEFT JOIN exact_posted_billing epb ON epb.maintenance_request_id = mr.id
            LEFT JOIN active_exact_invoice aei ON aei.maintenance_request_id = mr.id
            LEFT JOIN account_move legacy ON legacy.id = te.legacy_invoice_move_id
        """
