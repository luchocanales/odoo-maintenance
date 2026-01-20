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

    # Cobro (entre Evidencias y Conclusiones)
    technical_charge_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda (Cobro)",
        tracking=True,
        default=lambda self: self.env.company.currency_id.id,
    )
    technical_charge_amount = fields.Monetary(
        string="Monto a cobrar",
        currency_field="technical_charge_currency_id",
        tracking=True,
        default=0.0,
    )

    # Cierre
    technical_waiting_response_text = fields.Text(string="Mensaje / Cierre")
    technical_conclusions_html = fields.Html(string="Conclusiones", sanitize=False)

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------
    def _needs_technical_sequence(self):
        self.ensure_one()
        return not self.technical_report_number or self.technical_report_number in ("", "/")

    def _assign_technical_sequence_if_missing(self):
        """Asigna correlativo SOLO si falta."""
        for rec in self:
            if rec._needs_technical_sequence():
                rec.technical_report_number = self.env["ir.sequence"].sudo().next_by_code(
                    "maintenance.technical.report"
                ) or "N*PENDIENTE"

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
        product = self.env["product.product"].sudo().search(
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

    # ---------------------------------------------------------
    # Create / Write
    # ---------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("technical_report_number") or vals.get("technical_report_number") == "/":
                vals["technical_report_number"] = seq.next_by_code("maintenance.technical.report") or "/"

        records = super().create(vals_list)

        # Si nace con monto/moneda, sincroniza a extra_service_ids
        records._sync_charge_to_extra_service_ids(trigger_fields={"create"})
        return records

    def write(self, vals):
        # Cambios que deben disparar sync a vehicle.rental.extra.service
        sync_fields = {"technical_charge_amount", "technical_charge_currency_id"}

        must_sync = bool(sync_fields.intersection(vals.keys()))
        res = super().write(vals)

        # Evitar recursiones internas
        if self.env.context.get("skip_tr_seq") or self.env.context.get("skip_tr_charge_sync"):
            return res

        # Backfill correlativo para existentes (tu lógica actual solo asigna correlativo y retorna :contentReference[oaicite:1]{index=1})
        # Aquí lo mantenemos, pero además aprovechamos para re-sync porque description usa correlativo.
        missing = self.filtered(lambda r: not r.technical_report_number or r.technical_report_number in ("", "/"))
        if missing:
            seq = self.env["ir.sequence"].sudo()
            updates = {r.id: (seq.next_by_code("maintenance.technical.report") or "N*PENDIENTE") for r in missing}
            for r in missing.sudo():
                r.with_context(skip_tr_seq=True).write({"technical_report_number": updates[r.id]})
            must_sync = True

        if must_sync:
            self._sync_charge_to_extra_service_ids(trigger_fields=set(vals.keys()))

        return res

    # ---------------------------------------------------------
    # Sync -> vehicle.rental.line.extra_service_ids (vehicle.rental.extra.service)
    # ---------------------------------------------------------
    def _sync_charge_to_extra_service_ids(self, trigger_fields=None):
        """
        Crea/actualiza el registro en vehicle.rental.line.extra_service_ids (vehicle.rental.extra.service)
        relacionado a este informe (maintenance_request_id), con:
          - line.service_currency_id = technical_charge_currency_id :contentReference[oaicite:2]{index=2}
          - extra requiere: extra_date, product_id, product_qty :contentReference[oaicite:3]{index=3}
          - extra.amount = technical_charge_amount
          - extra.description = correlativo del informe
          - extra.product_id = 'Cargo por Daños y Desgaste'
        """
        trigger_fields = trigger_fields or set()

        # Si los modelos no están, no romper
        if "vehicle.rental.line" not in self.env or "vehicle.rental.extra.service" not in self.env:
            return

        Extra = self.env["vehicle.rental.extra.service"].sudo()

        for rec in self:
            if "vehicle_rental_line_id" not in rec._fields:
                continue

            line = rec.vehicle_rental_line_id
            if not line:
                continue

            # 1) Moneda de servicios en rental line (OPERACIONES)
            if rec.technical_charge_currency_id and "service_currency_id" in line._fields:
                line.with_context(skip_tr_charge_sync=True).sudo().write({
                    "service_currency_id": rec.technical_charge_currency_id.id
                })

            # 2) Buscar extra del informe (por maintenance_request_id, que agregamos por herencia)
            related = line.extra_service_ids.filtered(
                lambda x: hasattr(x, "maintenance_request_id") and x.maintenance_request_id.id == rec.id
            )

            product = rec._get_damage_wear_product()
            vals_extra = {
                "extra_date": fields.Date.context_today(rec),
                "product_id": product.id,
                "product_qty": 1.0,
                "amount": float(rec.technical_charge_amount or 0.0),
                "description": (rec.technical_report_number or "").strip(),
                "maintenance_request_id": rec.id,
            }

            if related:
                related[:1].with_context(skip_tr_charge_sync=True).sudo().write(vals_extra)
            else:
                # Crear por O2M (asigna vehicle_rental_line_id automáticamente)
                line.with_context(skip_tr_charge_sync=True).sudo().extra_service_ids.create(vals_extra)

    # ---------------------------------------------------------
    # Report
    # ---------------------------------------------------------
    def action_print_technical_report(self):
        self.ensure_one()
        return self.env.ref(
            "estratego_maintenance_technical_report.action_report_maintenance_technical"
        ).report_action(self)
