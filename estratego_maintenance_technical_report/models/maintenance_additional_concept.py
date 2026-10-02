# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MaintenanceAdditionalConcept(models.Model):
    _name = "maintenance.additional.concept"
    _description = "Concepto adicional de costo y venta de mantenimiento"
    _order = "concept_date, sequence, id"

    sequence = fields.Integer(string="Secuencia", default=10)
    maintenance_request_id = fields.Many2one(
        comodel_name="maintenance.request",
        string="Mantenimiento",
        required=True,
        ondelete="cascade",
        index=True,
    )
    concept_date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        help="Fecha operativa usada tanto para el costo analítico como para el Extra Operaciones.",
    )
    name = fields.Char(string="Concepto", required=True)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto",
        required=True,
        domain="[('sale_ok', '=', True), ('detailed_type', '=', 'service')]",
        default=lambda self: self._default_sale_product(),
        help=(
            "Producto que se utilizará al crear el Extra Operaciones. El concepto se conserva "
            "como descripción para que cada cargo sea identificable en la factura."
        ),
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda",
        related="maintenance_request_id.currency_id",
        readonly=True,
        store=False,
    )
    cost_amount = fields.Monetary(
        string="Costo",
        currency_field="currency_id",
        required=True,
        default=0.0,
        help=(
            "Costo final calculado externamente. Al enviar a facturación se convierte a moneda "
            "compañía y se registra como costo analítico del vehículo/contrato."
        ),
    )
    sale_amount = fields.Monetary(
        string="Venta",
        currency_field="currency_id",
        required=True,
        default=0.0,
        help=(
            "Monto final a presentar al cliente, incluido impuesto cuando corresponda. "
            "Se transforma al importe sin impuesto requerido por Extra Operaciones."
        ),
    )

    analytic_line_id = fields.Many2one(
        comodel_name="account.analytic.line",
        string="Costo analítico generado",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    extra_service_id = fields.Many2one(
        comodel_name="vehicle.rental.extra.service",
        string="Extra Operaciones generado",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    last_sent_cost_amount = fields.Monetary(
        string="Último costo enviado",
        currency_field="last_sent_currency_id",
        readonly=True,
        copy=False,
        default=0.0,
    )
    last_sent_sale_amount = fields.Monetary(
        string="Última venta enviada",
        currency_field="last_sent_currency_id",
        readonly=True,
        copy=False,
        default=0.0,
    )
    last_sent_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda del último envío",
        readonly=True,
        copy=False,
    )
    last_sent_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto del último envío",
        readonly=True,
        copy=False,
    )
    last_sent_name = fields.Char(
        string="Concepto del último envío",
        readonly=True,
        copy=False,
    )
    last_sent_at = fields.Datetime(
        string="Último envío",
        readonly=True,
        copy=False,
    )
    last_sent_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Usuario del último envío",
        readonly=True,
        copy=False,
    )
    billing_state = fields.Selection(
        [
            ("draft", "Pendiente"),
            ("pending_resend", "Pendiente de reenvío"),
            ("sent", "Presentado"),
            ("invoiced", "En factura"),
        ],
        string="Estado",
        compute="_compute_billing_state",
        readonly=True,
    )

    _sql_constraints = [
        (
            "maintenance_additional_concept_cost_non_negative",
            "CHECK(cost_amount >= 0)",
            "El costo del concepto no puede ser negativo.",
        ),
        (
            "maintenance_additional_concept_sale_non_negative",
            "CHECK(sale_amount >= 0)",
            "La venta del concepto no puede ser negativa.",
        ),
    ]

    @api.model
    def _default_sale_product(self):
        """Usa el producto histórico del flujo técnico cuando está disponible."""
        return self.env["product.product"].search(
            [
                ("name", "=", "Cargo por Daños y Desgaste"),
                ("detailed_type", "=", "service"),
                ("sale_ok", "=", True),
            ],
            limit=1,
        )

    @api.depends(
        "name",
        "product_id",
        "cost_amount",
        "sale_amount",
        "last_sent_at",
        "last_sent_cost_amount",
        "last_sent_sale_amount",
        "last_sent_currency_id",
        "last_sent_product_id",
        "last_sent_name",
        "analytic_line_id",
        "extra_service_id",
        "extra_service_id.invoice_line_ids.move_id.state",
        "extra_service_id.legacy_invoice_move_id.state",
    )
    def _compute_billing_state(self):
        for rec in self:
            if not rec.last_sent_at:
                rec.billing_state = "draft"
            elif rec.extra_service_id and rec.extra_service_id._get_active_invoice_moves():
                rec.billing_state = "invoiced"
            elif rec._needs_sync():
                rec.billing_state = "pending_resend"
            else:
                rec.billing_state = "sent"

    def _get_existing_extra(self):
        self.ensure_one()
        extra = self.extra_service_id
        if extra:
            return extra
        return self.env["vehicle.rental.extra.service"].sudo().search(
            [("maintenance_additional_concept_id", "=", self.id)],
            order="id",
            limit=1,
        )

    def _get_existing_analytic_line(self):
        self.ensure_one()
        analytic_line = self.analytic_line_id
        if analytic_line:
            return analytic_line
        return self.env["account.analytic.line"].sudo().search(
            [("maintenance_additional_concept_id", "=", self.id)],
            order="id",
            limit=1,
        )

    def _cost_needs_sync(self):
        self.ensure_one()
        if not self.last_sent_at or not self._get_existing_analytic_line():
            return True
        currency = self.currency_id or self.env.company.currency_id
        return not (
            self.last_sent_currency_id == currency
            and currency.compare_amounts(self.cost_amount, self.last_sent_cost_amount) == 0
        )

    def _sale_needs_sync(self):
        self.ensure_one()
        if not self.last_sent_at or not self._get_existing_extra():
            return True
        currency = self.currency_id or self.env.company.currency_id
        same_sale = (
            self.last_sent_currency_id == currency
            and currency.compare_amounts(self.sale_amount, self.last_sent_sale_amount) == 0
        )
        return not (
            same_sale
            and self.last_sent_product_id == self.product_id
            and (self.last_sent_name or "") == (self.name or "")
        )

    def _needs_sync(self):
        self.ensure_one()
        return self._cost_needs_sync() or self._sale_needs_sync()

    def _validate_for_send(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        if not self.product_id:
            raise ValidationError(_("Selecciona un producto de venta para el concepto '%s'.") % self.name)
        if currency.is_zero(self.cost_amount or 0.0) or self.cost_amount < 0:
            raise ValidationError(_("El costo del concepto '%s' debe ser mayor que cero.") % self.name)
        if currency.is_zero(self.sale_amount or 0.0) or self.sale_amount < 0:
            raise ValidationError(_("La venta del concepto '%s' debe ser mayor que cero.") % self.name)

        extra = self._get_existing_extra()
        if self.last_sent_at and extra and self._needs_sync():
            active_moves = extra._get_active_invoice_moves()
            if active_moves:
                raise ValidationError(_(
                    "No se puede modificar el concepto '%(concept)s' porque su Extra Operaciones "
                    "ya está incluido en una factura activa: %(invoices)s."
                ) % {
                    "concept": self.name,
                    "invoices": ", ".join(active_moves.mapped("display_name")),
                })
        return True

    def _prepare_analytic_line_vals(self):
        self.ensure_one()
        maintenance = self.maintenance_request_id
        company = maintenance.company_id or self.env.company
        vehicle_account = maintenance.fleet_vehicle_id.analytic_account_id
        if not vehicle_account:
            raise ValidationError(_(
                "El vehículo '%s' no tiene una cuenta analítica configurada."
            ) % maintenance.fleet_vehicle_id.display_name)

        company_currency = company.currency_id
        source_currency = self.currency_id or company_currency
        amount_company = source_currency._convert(
            self.cost_amount,
            company_currency,
            company,
            self.concept_date or fields.Date.context_today(self),
        )

        AnalyticLine = self.env["account.analytic.line"]
        vals = {
            "name": "%s | %s" % (maintenance.display_name, self.name),
            "date": self.concept_date or fields.Date.context_today(self),
            "amount": -abs(amount_company),
            "unit_amount": 1.0,
            "company_id": company.id,
            "maintenance_additional_concept_id": self.id,
        }
        if "ref" in AnalyticLine._fields:
            vals["ref"] = maintenance.display_name

        # Se respetan los dos ejes analíticos usados por el proyecto Maroal:
        # vehículo y contrato/liquidación. Cada cuenta se coloca en la columna
        # dinámica correspondiente a su plan analítico.
        analytic_accounts = vehicle_account
        contract_account = maintenance.order_id.analytic_account_id
        if contract_account:
            analytic_accounts |= contract_account
        for account in analytic_accounts:
            column_name = account.plan_id._column_name()
            if column_name in AnalyticLine._fields:
                vals[column_name] = account.id

        # Compatibilidad con reportes históricos del proyecto que clasifican los
        # costos analíticos de operación bajo la categoría vendor_bill.
        category_field = AnalyticLine._fields.get("category")
        if category_field and hasattr(category_field, "_description_selection"):
            available = dict(category_field._description_selection(self.env))
            if "vendor_bill" in available:
                vals["category"] = "vendor_bill"
        return vals

    def _sync_analytic_cost(self):
        self.ensure_one()
        vals = self._prepare_analytic_line_vals()
        analytic_line = self._get_existing_analytic_line()
        if analytic_line:
            analytic_line.with_context(
                skip_additional_concept_analytic_sync=True
            ).sudo().write(vals)
        else:
            analytic_line = self.env["account.analytic.line"].sudo().create(vals)
        if self.analytic_line_id != analytic_line:
            self.with_context(skip_additional_concept_protection=True).sudo().write({
                "analytic_line_id": analytic_line.id,
            })
        return analytic_line

    def _sale_amount_without_tax(self):
        self.ensure_one()
        maintenance = self.maintenance_request_id
        company = maintenance.company_id or self.env.company
        currency = self.currency_id or company.currency_id
        taxes = self.product_id.taxes_id.filtered(
            lambda tax: not tax.company_id or tax.company_id == company
        )
        if not taxes:
            return self.sale_amount
        result = taxes.with_company(company).with_context(force_price_include=True).compute_all(
            self.sale_amount,
            currency=currency,
            quantity=1.0,
            product=self.product_id,
            partner=maintenance.order_id.partner_id,
        )
        return float(result["total_excluded"])

    def _sync_extra_service(self, rental_line):
        self.ensure_one()
        maintenance = self.maintenance_request_id
        currency = self.currency_id or maintenance.company_id.currency_id
        extra = self._get_existing_extra()

        # Extra Operaciones comparte moneda a nivel de vehicle.rental.line. No se
        # cambia silenciosamente si existen otros cargos con una moneda distinta.
        if rental_line.service_currency_id and rental_line.service_currency_id != currency:
            other_extras = rental_line.extra_service_ids - extra
            if other_extras:
                raise ValidationError(_(
                    "La línea de alquiler ya tiene Extras Operaciones en moneda %(current)s. "
                    "No es seguro cambiarla automáticamente a %(new)s porque afectaría otros cargos."
                ) % {
                    "current": rental_line.service_currency_id.display_name,
                    "new": currency.display_name,
                })
        if rental_line.service_currency_id != currency:
            rental_line.with_context(skip_tr_charge_sync=True).sudo().write({
                "service_currency_id": currency.id,
            })

        report_number = (maintenance.technical_report_number or "").strip()
        description = "%s - %s" % (report_number, self.name) if report_number else self.name
        vals = {
            "product_id": self.product_id.id,
            "product_qty": 1.0,
            "amount": self._sale_amount_without_tax(),
            "description": description,
            "vehicle_rental_line_id": rental_line.id,
            "maintenance_additional_concept_id": self.id,
        }
        if extra:
            extra.with_context(skip_tr_charge_sync=True).sudo().write(vals)
        else:
            vals["extra_date"] = self.concept_date or fields.Date.context_today(self)
            extra = self.env["vehicle.rental.extra.service"].with_context(
                skip_tr_charge_sync=True
            ).sudo().create(vals)

        if self.extra_service_id != extra:
            self.with_context(skip_additional_concept_protection=True).sudo().write({
                "extra_service_id": extra.id,
            })
        return extra

    def _send(self, rental_line):
        self.ensure_one()
        self._validate_for_send()
        cost_needs_sync = self._cost_needs_sync()
        sale_needs_sync = self._sale_needs_sync()
        if not cost_needs_sync and not sale_needs_sync:
            return False

        if cost_needs_sync:
            self._sync_analytic_cost()
        elif (self.last_sent_name or "") != (self.name or ""):
            analytic_line = self._get_existing_analytic_line()
            if analytic_line:
                vals = {"name": "%s | %s" % (self.maintenance_request_id.display_name, self.name)}
                if "ref" in analytic_line._fields:
                    vals["ref"] = self.maintenance_request_id.display_name
                analytic_line.with_context(
                    skip_additional_concept_analytic_sync=True
                ).sudo().write(vals)

        if sale_needs_sync:
            self._sync_extra_service(rental_line)

        self.with_context(skip_additional_concept_protection=True).sudo().write({
            "last_sent_cost_amount": self.cost_amount,
            "last_sent_sale_amount": self.sale_amount,
            "last_sent_currency_id": self.currency_id.id,
            "last_sent_product_id": self.product_id.id,
            "last_sent_name": self.name,
            "last_sent_at": fields.Datetime.now(),
            "last_sent_user_id": self.env.user.id,
        })
        return True

    def write(self, vals):
        protected = {
            "maintenance_request_id",
            "concept_date",
            "name",
            "product_id",
            "cost_amount",
            "sale_amount",
        }
        if protected.intersection(vals) and not self.env.context.get("skip_additional_concept_protection"):
            for rec in self.filtered("last_sent_at"):
                if "concept_date" in vals and vals.get("concept_date") != rec.concept_date:
                    raise ValidationError(_(
                        "La fecha del concepto '%s' queda congelada después del primer envío "
                        "para conservar la fecha operativa del costo y del Extra Operaciones."
                    ) % rec.name)
                active_moves = rec._get_existing_extra()._get_active_invoice_moves()
                if active_moves:
                    raise ValidationError(_(
                        "No se puede modificar el concepto '%(concept)s' porque ya está incluido "
                        "en una factura activa: %(invoices)s."
                    ) % {
                        "concept": rec.name,
                        "invoices": ", ".join(active_moves.mapped("display_name")),
                    })
        return super().write(vals)

    def unlink(self):
        sent = self.filtered("last_sent_at")
        if sent:
            raise ValidationError(_(
                "No se puede eliminar un concepto que ya fue enviado. Si aún no está facturado, "
                "corrige sus importes y vuelve a usar 'Enviar a facturación' para conservar la trazabilidad."
            ))
        return super().unlink()


class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    maintenance_additional_concept_id = fields.Many2one(
        comodel_name="maintenance.additional.concept",
        string="Concepto adicional de mantenimiento",
        readonly=True,
        copy=False,
        index=True,
        ondelete="restrict",
    )

    _sql_constraints = [
        (
            "maintenance_additional_concept_analytic_unique",
            "unique(maintenance_additional_concept_id)",
            "Un concepto adicional de mantenimiento solo puede generar una línea analítica.",
        ),
    ]

    def write(self, vals):
        if not self.env.context.get("skip_additional_concept_analytic_sync"):
            protected = self.filtered("maintenance_additional_concept_id")
            if protected:
                raise ValidationError(_(
                    "Las líneas analíticas generadas desde conceptos de mantenimiento no se modifican directamente. "
                    "Realiza la corrección en el mantenimiento y vuelve a usar 'Enviar a facturación'."
                ))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get("skip_additional_concept_analytic_sync"):
            protected = self.filtered("maintenance_additional_concept_id")
            if protected:
                raise ValidationError(_(
                    "No se puede eliminar una línea analítica generada desde un concepto de mantenimiento."
                ))
        return super().unlink()
