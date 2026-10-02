# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MaintenanceTechnicalEvidence(models.Model):
    _name = "maintenance.technical.evidence"
    _description = "Evidencia fotográfica - Informe Técnico"
    _order = "sequence, id"

    maintenance_request_id = fields.Many2one(
        comodel_name="maintenance.request",
        string="Solicitud de mantenimiento",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Título")
    description = fields.Text(string="Descripción")
    image = fields.Image(string="Imagen", max_width=1920, max_height=1920)


class MaintenanceRequest(models.Model):
    _inherit = "maintenance.request"

    technical_report_number = fields.Char(
        string="N° Informe Técnico",
        copy=False,
        readonly=True,
        default="/",
    )

    # Sección 3
    technical_evaluation_html = fields.Html(string="3. Evaluación", sanitize=False)

    # Sección 4 (Sistemas evaluados)
    eval_engine = fields.Boolean(string="Motor")
    eval_steering = fields.Boolean(string="Dirección")
    eval_suspension = fields.Boolean(string="Suspensión")
    eval_tires = fields.Boolean(string="Llantas")
    eval_transmission = fields.Boolean(string="Transmisión")
    eval_electrical = fields.Boolean(string="Eléctrico")
    eval_brakes = fields.Boolean(string="Frenos")
    eval_chassis = fields.Boolean(string="Chasis")

    # Sección 5
    technical_introduction_html = fields.Html(string="5. Introducción", sanitize=False)

    # Sección 6 (Evidencias)
    technical_evidence_ids = fields.One2many(
        comodel_name="maintenance.technical.evidence",
        inverse_name="maintenance_request_id",
        string="Evidencias",
    )

    # Cobro
    technical_charge_currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="currency_id",
        string="Moneda (Cobro)",
        readonly=True
    )

    technical_charge_amount = fields.Monetary(
        string="Monto a cobrar",
        currency_field="technical_charge_currency_id",
        tracking=True,
        default=0.0,
    )
    technical_charge_last_sent_amount = fields.Monetary(
        string="Último monto enviado",
        currency_field="technical_charge_last_sent_currency_id",
        readonly=True,
        copy=False,
        default=0.0,
    )
    technical_charge_last_sent_currency_id = fields.Many2one(
        'res.currency',
        string="Moneda del último envío",
        readonly=True,
        copy=False,
    )
    technical_charge_last_sent_at = fields.Datetime(
        string="Último envío a facturación",
        readonly=True,
        copy=False,
    )
    technical_charge_last_sent_user_id = fields.Many2one(
        'res.users',
        string="Usuario del último envío",
        readonly=True,
        copy=False,
    )
    technical_charge_extra_service_ids = fields.One2many(
        comodel_name="vehicle.rental.extra.service",
        inverse_name="maintenance_request_id",
        string="Extras Operaciones de Partes/Servicios",
        readonly=True,
        copy=False,
    )
    parts_services_billing_state = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("submitted", "Presentado"),
            ("in_invoice", "En factura"),
            ("invoiced", "Facturado"),
        ],
        string="Estado",
        compute="_compute_parts_services_billing_state",
        readonly=True,
    )

    additional_concept_ids = fields.One2many(
        comodel_name="maintenance.additional.concept",
        inverse_name="maintenance_request_id",
        string="Conceptos adicionales",
        copy=True,
    )
    total_additional_concept_actual_cost = fields.Monetary(
        string="Costo Real Conceptos Adicionales",
        currency_field="currency_id",
        compute="_compute_actual_costs",
        readonly=True,
        help="Suma de los costos adicionales efectivamente enviados y registrados analíticamente.",
    )

    technical_cost_table = fields.Html(string="Tabla de Costos", sanitize=False)

    # Cierre
    technical_waiting_response_text = fields.Text(string="Mensaje / Cierre")
    technical_conclusions_html = fields.Html(string="Conclusiones", sanitize=False)

    # Firma
    supervisor_signature_html = fields.Html(
        string="Firma Supervisor",
        compute="_compute_supervisor_public",
        compute_sudo=True,
    )

    supervisor_name = fields.Char(string="Supervisor", compute="_compute_supervisor_public", compute_sudo=True)
    responsible_name = fields.Char(string="Responsable", compute="_compute_supervisor_public", compute_sudo=True)
    # ---------------------------
    # Helpers
    # ---------------------------
    @api.depends(
        "technical_charge_last_sent_at",
        "technical_charge_extra_service_ids.invoice_line_ids.move_id.state",
        "technical_charge_extra_service_ids.invoice_line_ids.move_id.move_type",
        "technical_charge_extra_service_ids.legacy_invoice_move_id.state",
        "technical_charge_extra_service_ids.legacy_invoice_move_id.move_type",
    )
    def _compute_parts_services_billing_state(self):
        """Estado comercial del bloque Partes y Servicios.

        El cobro estándar del mantenimiento se consolida en un único Extra Operaciones;
        por eso todas las líneas de partes/servicios comparten este mismo estado.
        """
        for rec in self:
            extras = rec.technical_charge_extra_service_ids
            active_moves = extras._get_active_invoice_moves() if extras else self.env["account.move"]
            posted_moves = active_moves.filtered(
                lambda move: move.state == "posted"
                and move.move_type in ("out_invoice", "out_receipt")
            )
            if posted_moves:
                rec.parts_services_billing_state = "invoiced"
            elif active_moves:
                rec.parts_services_billing_state = "in_invoice"
            elif rec.technical_charge_last_sent_at or extras:
                rec.parts_services_billing_state = "submitted"
            else:
                rec.parts_services_billing_state = "pending"

    @api.depends("supervisor_employee_id")
    def _compute_supervisor_public(self):
        Employee = self.env["hr.employee"].sudo()
        for rec in self:
            rec.supervisor_signature_html = False
            rec.supervisor_name = False
            rec.responsible_name = False
            if not rec.supervisor_employee_id:
                continue

            if not rec.responsible_employee_id:
                continue
    
            emp = Employee.browse(rec.supervisor_employee_id.id)
            rec.supervisor_signature_html = emp.signature_html or False
            rec.supervisor_name = emp.name or False

            emp = Employee.browse(rec.responsible_employee_id.id)
            rec.responsible_name = emp.name or False


    @api.depends(
        'maintenance_part_ids.actual_cost',
        'maintenance_service_ids.actual_service_cost',
        'sub_total_charge',
        'additional_concept_ids.last_sent_cost_amount',
        'additional_concept_ids.last_sent_at',
    )
    def _compute_actual_costs(self):
        # Mantiene el cálculo estándar de partes/servicios y agrega únicamente los
        # conceptos que ya fueron publicados mediante "Enviar a facturación".
        super()._compute_actual_costs()
        for rec in self:
            additional_actual = sum(
                line.last_sent_cost_amount
                for line in rec.additional_concept_ids
                if line.last_sent_at
            )
            rec.total_additional_concept_actual_cost = additional_actual
            rec.total_actual_cost = (rec.total_actual_cost or 0.0) + additional_actual

            # El concepto adicional nace ya como costo real, no como presupuesto.
            # Para no deformar la desviación de partes/servicios, se incorpora al
            # denominador base con el mismo valor que fue enviado.
            planned_total = (rec.sub_total_charge or 0.0) + additional_actual
            variance = rec.total_actual_cost - planned_total
            rec.cost_variance = variance
            rec.cost_variance_percent = (
                (variance / planned_total) * 100.0 if planned_total else 0.0
            )

    def _get_schedule_date_str(self):
        self.ensure_one()
        dt = self.schedule_date or fields.Datetime.now()
        return dt.strftime("%d/%m/%Y")

    def _get_damage_wear_product(self):
        """
        Producto obligatorio para crear vehicle.rental.extra.service:
        Nombre exacto: 'Cargo por Daños y Desgaste'
        Tipo: service
        sale_ok: True
        """
        Product = self.env["product.product"].sudo()
        product = Product.search(
            [
                ("name", "=", "Cargo por Daños y Desgaste"),
                ("detailed_type", "=", "service"),
                ("sale_ok", "=", True),
            ],
            limit=1,
        )
        if not product:
            raise ValidationError(_(
                "No se encontró el producto requerido: 'Cargo por Daños y Desgaste'.\n"
                "Crea un producto de tipo Servicio con ese nombre exacto y habilita 'Puede venderse'."
            ))
        return product

    # ---------------------------
    # Correlativo
    # ---------------------------
    def _needs_technical_sequence(self):
        """True si el correlativo está vacío o en '/'. """
        self.ensure_one()
        return not self.technical_report_number or self.technical_report_number in ("", "/")

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("technical_report_number") or vals.get("technical_report_number") == "/":
                vals["technical_report_number"] = seq.next_by_code("maintenance.technical.report") or "/"
        # El monto técnico ya NO se sincroniza automáticamente.
        return super().create(vals_list)

    def write(self, vals):
        # El bloque Partes/Servicios y los Adicionales tienen ciclos de facturación
        # independientes. Una vez que el cargo consolidado de Partes/Servicios entra
        # en una factura activa, su monto no puede alterarse, pero esto no bloquea
        # registrar/modificar/enviar conceptos adicionales todavía no facturados.
        if "technical_charge_amount" in vals and not self.env.context.get("skip_tr_charge_sync"):
            for rec in self:
                company = rec.company_id or self.env.company
                currency = rec.technical_charge_currency_id or company.currency_id
                new_amount = vals.get("technical_charge_amount") or 0.0
                if (
                    currency.compare_amounts(new_amount, rec.technical_charge_amount or 0.0) != 0
                    and rec.parts_services_billing_state in ("in_invoice", "invoiced")
                ):
                    raise ValidationError(_(
                        "No se puede modificar el monto de Partes y Servicios porque ya está "
                        "incluido en una factura activa. Los conceptos de la pestaña Adicionales "
                        "pueden seguir registrándose y enviándose de forma independiente."
                    ))

        # Después del primer envío se congela la relación comercial y su moneda.
        # Mover el mantenimiento a otro contrato/vehículo rompería la trazabilidad
        # tanto del cargo técnico como de los conceptos adicionales.
        protected_link_fields = {
            'order_id', 'fleet_vehicle_id', 'vehicle_rental_line_id', 'currency_id'
        }
        if protected_link_fields.intersection(vals) and not self.env.context.get('allow_technical_charge_link_change'):
            for rec in self:
                has_sent_financial_data = bool(
                    rec.technical_charge_last_sent_at
                    or rec.additional_concept_ids.filtered('last_sent_at')
                )
                if not has_sent_financial_data:
                    continue
                for field_name in protected_link_fields.intersection(vals):
                    current = rec[field_name]
                    current_value = current.id if getattr(current, 'id', False) else current or False
                    new_value = vals.get(field_name) or False
                    if current_value != new_value:
                        raise ValidationError(_(
                            "No se puede cambiar la orden, el vehículo, la línea de alquiler ni la moneda "
                            "después de haber enviado información de costo/venta a facturación."
                        ))

        res = super().write(vals)

        if self.env.context.get("skip_tr_seq"):
            return res

        # Backfill de correlativo para registros históricos. Ya no dispara facturación.
        missing = self.filtered(lambda r: not r.technical_report_number or r.technical_report_number in ("", "/"))
        if missing:
            seq = self.env["ir.sequence"].sudo()
            for rec in missing.sudo():
                rec.with_context(skip_tr_seq=True).write({
                    "technical_report_number": seq.next_by_code("maintenance.technical.report") or "N*PENDIENTE"
                })
        return res


    def _get_amount_without_tax(self, amount, product, partner=None, currency=None, company=None):
        """Devuelve el monto sin impuestos a partir de un monto ingresado (posiblemente con impuesto incluido)."""
        amount = float(amount or 0.0)
        if not amount or not product:
            return amount

        company = company or self.company_id or self.env.company
        currency = currency or (company.currency_id if company else self.env.company.currency_id)

        # Impuestos de venta del producto, filtrados por compañía (si corresponde)
        taxes = product.taxes_id
        if company and "company_id" in taxes._fields:
            taxes = taxes.filtered(lambda t: not t.company_id or t.company_id == company)

        # Mapear por posición fiscal del partner (si existe)
        fpos = getattr(partner, "property_account_position_id", False) if partner else False
        if fpos and hasattr(fpos, "map_tax"):
            taxes = fpos.map_tax(taxes, product, partner)

        if not taxes:
            return amount

        # compute_all maneja price_include / price_exclude automáticamente
        res = taxes.with_company(company).compute_all(
            amount,
            currency=currency,
            quantity=1.0,
            product=product,
            partner=partner,
        )
        return float(res.get("total_excluded", amount))


    # ---------------------------
    # Sync con vehicle.rental.line.extra_service_ids (vehicle.rental.extra.service)
    # ---------------------------
    def _sync_charge_to_extra_service_ids(self):
        """Crea o reemplaza el único Extra Operaciones asociado al informe.

        Esta rutina ya no se invoca desde ``create``/``write``: únicamente desde el
        botón ``Enviar a facturación``. En reemplazos conserva ``extra_date`` original.
        """
        self.ensure_one()
        if "vehicle.rental.line" not in self.env or "vehicle.rental.extra.service" not in self.env:
            raise ValidationError(_("El módulo de alquiler de vehículos no está disponible."))

        Extra = self.env["vehicle.rental.extra.service"].sudo()
        if "maintenance_request_id" not in Extra._fields:
            raise ValidationError(_(
                "Falta el campo 'maintenance_request_id' en 'vehicle.rental.extra.service'. "
                "Actualiza el módulo Informe Técnico de Mantenimiento."
            ))

        line = self.vehicle_rental_line_id
        currency = self.technical_charge_currency_id
        product = self._get_damage_wear_product()

        extras = Extra.search([
            ("vehicle_rental_line_id", "=", line.id),
            ("maintenance_request_id", "=", self.id),
        ], order='id')
        if len(extras) > 1:
            raise ValidationError(_(
                "Se encontraron varios Extras Operaciones asociados al mismo informe técnico. "
                "Regulariza los datos antes de volver a enviar a facturación."
            ))
        extra = extras[:1]

        # La moneda de Extra Operaciones es compartida por la línea de alquiler. No
        # sobreescribimos otras operaciones silenciosamente.
        if line.service_currency_id and line.service_currency_id != currency:
            other_extras = line.extra_service_ids - extra
            if other_extras:
                raise ValidationError(_(
                    "La línea de alquiler ya tiene Extras Operaciones en moneda %s. "
                    "No es seguro cambiarla automáticamente a %s porque afectaría otros cargos."
                ) % (line.service_currency_id.display_name, currency.display_name))

        if currency and line.service_currency_id != currency:
            line.with_context(skip_tr_charge_sync=True).sudo().write({
                "service_currency_id": currency.id,
            })

        amount_included = float(self.technical_charge_amount or 0.0)
        taxes = product.taxes_id.filtered(
            lambda tax: not tax.company_id or tax.company_id == self.company_id
        )
        if taxes and amount_included:
            tax_res = taxes.with_company(self.company_id).with_context(force_price_include=True).compute_all(
                amount_included,
                currency=currency,
                quantity=1.0,
                product=product,
                partner=getattr(self, "partner_id", False),
            )
            amount_value = float(tax_res["total_excluded"])
        else:
            amount_value = amount_included

        vals = {
            "product_id": product.id,
            "product_qty": 1.0,
            "amount": amount_value,
            "description": (self.technical_report_number or "").strip(),
        }
        if extra:
            # Reemplazo: misma línea, misma identidad y MISMA fecha operativa.
            extra.with_context(skip_tr_charge_sync=True).write(vals)
        else:
            vals.update({
                "vehicle_rental_line_id": line.id,
                "maintenance_request_id": self.id,
                "extra_date": fields.Date.context_today(self),
            })
            extra = Extra.with_context(skip_tr_charge_sync=True).create(vals)
        return extra

    def _format_charge_for_message(self, amount, currency):
        currency = currency or self.env.company.currency_id
        decimals = currency.decimal_places if currency else 2
        return "%s %.*f" % (currency.name or currency.symbol or '', decimals, amount or 0.0)

    def _get_rental_line_for_billing(self):
        self.ensure_one()
        if not self.fleet_vehicle_id:
            raise ValidationError(_("Selecciona un vehículo antes de enviar a facturación."))
        if not self.order_id:
            raise ValidationError(_("Selecciona una orden de alquiler antes de enviar a facturación."))
        if self.order_id.state != 'sale':
            raise ValidationError(_("La orden de alquiler debe estar confirmada antes de enviar a facturación."))

        rental_line = self.env['vehicle.rental.line'].search([
            ('order_id', '=', self.order_id.id),
            ('vehicle_id', '=', self.fleet_vehicle_id.id),
        ], order='id desc', limit=1)
        if not rental_line:
            raise ValidationError(_(
                "El vehículo '%s' no forma parte de la orden '%s'."
            ) % (self.fleet_vehicle_id.display_name, self.order_id.display_name))

        if self.vehicle_rental_line_id != rental_line:
            has_previous_send = bool(
                self.technical_charge_last_sent_at
                or self.additional_concept_ids.filtered('last_sent_at')
            )
            if has_previous_send:
                raise ValidationError(_(
                    "La línea de alquiler vinculada al mantenimiento ya no coincide con la orden/vehículo "
                    "usados en un envío anterior."
                ))
            self.with_context(allow_technical_charge_link_change=True).write({
                'vehicle_rental_line_id': rental_line.id,
            })
        return rental_line

    def _technical_charge_needs_sync(self):
        self.ensure_one()
        currency = self.technical_charge_currency_id or self.env.company.currency_id
        amount = self.technical_charge_amount or 0.0
        if not self.technical_charge_last_sent_at:
            return not currency.is_zero(amount) and amount > 0.0
        if currency.is_zero(amount) or amount < 0.0:
            raise ValidationError(_(
                "El cargo técnico ya fue enviado anteriormente y no puede dejarse en cero. "
                "Si debe anularse, regulariza primero el Extra/factura vinculada."
            ))
        return not (
            self.technical_charge_last_sent_currency_id == currency
            and currency.compare_amounts(amount, self.technical_charge_last_sent_amount) == 0
        )

    def _validate_technical_charge_resend(self, rental_line):
        self.ensure_one()
        if not self._technical_charge_needs_sync():
            return False
        currency = self.technical_charge_currency_id or self.env.company.currency_id
        if currency.is_zero(self.technical_charge_amount or 0.0) or self.technical_charge_amount < 0:
            raise ValidationError(_("El monto a cobrar debe ser mayor que cero."))

        existing = self.env['vehicle.rental.extra.service'].sudo().search([
            ('vehicle_rental_line_id', '=', rental_line.id),
            ('maintenance_request_id', '=', self.id),
        ], order='id')
        if len(existing) > 1:
            raise ValidationError(_(
                "Se encontraron varios Extras Operaciones asociados al informe técnico. "
                "Regulariza los datos antes de continuar."
            ))
        existing = existing[:1]
        if self.technical_charge_last_sent_at and existing:
            active_invoice_moves = existing._get_active_invoice_moves()
            if active_invoice_moves:
                raise ValidationError(_(
                    "No se puede modificar el cargo técnico porque ya está incluido en una factura activa: %s."
                ) % ', '.join(active_invoice_moves.mapped('display_name')))
        return True

    def _send_technical_charge(self):
        self.ensure_one()
        currency = self.technical_charge_currency_id or self.env.company.currency_id
        had_previous_send = bool(self.technical_charge_last_sent_at)
        previous_amount = self.technical_charge_last_sent_amount
        previous_currency = self.technical_charge_last_sent_currency_id

        self._sync_charge_to_extra_service_ids()
        self.write({
            'technical_charge_last_sent_amount': self.technical_charge_amount,
            'technical_charge_last_sent_currency_id': currency.id,
            'technical_charge_last_sent_at': fields.Datetime.now(),
            'technical_charge_last_sent_user_id': self.env.user.id,
        })
        current_label = self._format_charge_for_message(self.technical_charge_amount, currency)
        if had_previous_send:
            previous_label = self._format_charge_for_message(previous_amount, previous_currency)
            return _(
                "Cargo técnico reemplazado para facturación: %s → %s."
            ) % (previous_label, current_label)
        return _("Cargo técnico enviado a facturación: %s.") % current_label

    def action_send_technical_charge_to_invoice(self):
        """Publica en una única acción las consecuencias de costo y venta.

        - Cargo técnico: conserva el flujo histórico de Extra Operaciones.
        - Conceptos adicionales: crea/actualiza un costo analítico y un Extra
          Operaciones por concepto.
        - Si una fuente ya está dentro de una factura activa, solo bloquea cuando
          existe un cambio que intentaría modificar lo previamente facturado.
        """
        self.ensure_one()
        if (self.technical_charge_amount or 0.0) < 0.0:
            raise ValidationError(_("El monto técnico no puede ser negativo."))
        if not self.technical_charge_amount and not self.additional_concept_ids:
            raise ValidationError(_(
                "No hay un cargo técnico ni conceptos adicionales para enviar."
            ))

        rental_line = self._get_rental_line_for_billing()
        technical_needs_sync = self._technical_charge_needs_sync()
        if technical_needs_sync:
            self._validate_technical_charge_resend(rental_line)

        concept_changes = self.additional_concept_ids.filtered(lambda line: line._needs_sync())
        for concept in concept_changes:
            concept._validate_for_send()

        if not technical_needs_sync and not concept_changes:
            raise ValidationError(_(
                "No hay nuevos conceptos ni cambios pendientes de enviar a facturación."
            ))

        messages = []
        if technical_needs_sync:
            messages.append(self._send_technical_charge())

        for concept in concept_changes:
            was_sent = bool(concept.last_sent_at)
            if concept._send(rental_line):
                action = _("actualizado") if was_sent else _("enviado")
                messages.append(_(
                    "Concepto '%(concept)s' %(action)s: costo %(cost)s / venta %(sale)s."
                ) % {
                    'concept': concept.name,
                    'action': action,
                    'cost': self._format_charge_for_message(concept.cost_amount, concept.currency_id),
                    'sale': self._format_charge_for_message(concept.sale_amount, concept.currency_id),
                })

        # Texto plano deliberadamente: no introducir etiquetas HTML en el chatter.
        self.message_post(body="\n".join(messages), subtype_xmlid='mail.mt_note')
        return True

    def unlink(self):
        for rec in self:
            if rec.additional_concept_ids.filtered('last_sent_at'):
                raise ValidationError(_(
                    "No se puede eliminar este mantenimiento porque tiene conceptos adicionales "
                    "que ya generaron costo analítico y Extra Operaciones."
                ))
        return super().unlink()

    # ---------------------------
    # Acción reporte
    # ---------------------------
    def action_print_technical_report(self):
        self.ensure_one()
        return self.env.ref(
            "estratego_maintenance_technical_report.action_report_maintenance_technical"
        ).report_action(self)


class MaintenancePart(models.Model):
    _inherit = "maintenance.part"

    customer_billing_state = fields.Selection(
        related="maintenance_request_id.parts_services_billing_state",
        string="Estado",
        readonly=True,
        store=False,
        help=(
            "Estado de facturación al cliente del bloque consolidado Partes y Servicios "
            "del mantenimiento."
        ),
    )


class MaintenanceService(models.Model):
    _inherit = "maintenance.service"

    customer_billing_state = fields.Selection(
        related="maintenance_request_id.parts_services_billing_state",
        string="Estado",
        readonly=True,
        store=False,
        help=(
            "Estado de facturación al cliente del bloque consolidado Partes y Servicios "
            "del mantenimiento."
        ),
    )
