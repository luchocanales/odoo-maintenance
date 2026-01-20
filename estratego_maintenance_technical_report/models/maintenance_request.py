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

    # ---------------------------
    # Helpers
    # ---------------------------
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

        records = super().create(vals_list)

        # Si ya nace con monto/moneda, sincroniza
        records._sync_charge_to_extra_service_ids(trigger_fields={"create"})
        return records

    def write(self, vals):
        # Dispara sync si cambia monto/moneda o correlativo (porque description depende del correlativo)
        sync_fields = {"technical_charge_amount", "technical_charge_currency_id", "technical_report_number"}
        must_sync = bool(sync_fields.intersection(vals.keys()))

        res = super().write(vals)

        # Evitar recursión del correlativo
        if self.env.context.get("skip_tr_seq"):
            return res

        # Backfill correlativo para existentes (si aún está vacío o '/')
        missing = self.filtered(lambda r: not r.technical_report_number or r.technical_report_number in ("", "/"))
        if missing:
            seq = self.env["ir.sequence"].sudo()
            for r in missing.sudo():
                r.with_context(skip_tr_seq=True).write(
                    {"technical_report_number": seq.next_by_code("maintenance.technical.report") or "N*PENDIENTE"}
                )
            must_sync = True  # description del extra depende del correlativo

        # Sync cargo -> vehicle.rental.extra.service
        if must_sync and not self.env.context.get("skip_tr_charge_sync"):
            self._sync_charge_to_extra_service_ids(trigger_fields=set(vals.keys()))

        return res

    # ---------------------------
    # Sync con vehicle.rental.line.extra_service_ids (vehicle.rental.extra.service)
    # ---------------------------
    def _sync_charge_to_extra_service_ids(self, trigger_fields=None):
        """
        Crea/actualiza un registro en vehicle.rental.line.extra_service_ids (vehicle.rental.extra.service)
        relacionado a este informe (maintenance_request_id), con:
          - line.service_currency_id = technical_charge_currency_id
          - extra.amount = technical_charge_amount
          - extra.description = technical_report_number
          - extra.product_id = producto 'Cargo por Daños y Desgaste'
          - extra.extra_date = hoy (required)
          - extra.product_qty = 1 (required)
        """
        trigger_fields = trigger_fields or set()

        # Si no existe el modelo de rental, salir sin romper
        if "vehicle.rental.line" not in self.env or "vehicle.rental.extra.service" not in self.env:
            return

        Extra = self.env["vehicle.rental.extra.service"].sudo()

        # ✅ HARD CHECK: ya que decidiste quedarte con herencia, este campo DEBE existir
        if "maintenance_request_id" not in Extra._fields:
            raise ValidationError(_(
                "Falta el campo 'maintenance_request_id' en 'vehicle.rental.extra.service'.\n"
                "Esto indica que la herencia no está cargando (revisa __init__.py / __manifest__.py depends / upgrade del módulo)."
            ))

        for rec in self:
            if "vehicle_rental_line_id" not in rec._fields:
                continue

            line = rec.vehicle_rental_line_id
            if not line:
                continue

            currency = rec.technical_charge_currency_id
            amount_value = float(rec.technical_charge_amount or 0.0)
            description_value = (rec.technical_report_number or "").strip()

            # 1) Setear moneda de servicios (Operaciones) en la línea rental
            if currency and "service_currency_id" in line._fields:
                line.with_context(skip_tr_charge_sync=True).sudo().write({"service_currency_id": currency.id})

            # 2) Buscar el extra EXACTO de este informe (sin depender del one2many cache)
            extra = Extra.search(
                [
                    ("vehicle_rental_line_id", "=", line.id),
                    ("maintenance_request_id", "=", rec.id),
                ],
                limit=1,
            )

            product = rec._get_damage_wear_product()

            vals_to_set = {
                "vehicle_rental_line_id": line.id,  # ✅ explícito para evitar registros “sueltos”
                "maintenance_request_id": rec.id,   # ✅ vínculo determinístico
                "extra_date": fields.Date.context_today(rec),  # required en el modelo :contentReference[oaicite:3]{index=3}
                "product_id": product.id,                    # required :contentReference[oaicite:4]{index=4}
                "product_qty": 1.0,                          # required :contentReference[oaicite:5]{index=5}
                "amount": amount_value,
                "description": description_value,
            }

            if extra:
                # no actualices vehicle_rental_line_id/maintenance_request_id si ya existe (por orden/seguridad)
                extra.with_context(skip_tr_charge_sync=True).write({
                    "extra_date": vals_to_set["extra_date"],
                    "product_id": vals_to_set["product_id"],
                    "product_qty": vals_to_set["product_qty"],
                    "amount": vals_to_set["amount"],
                    "description": vals_to_set["description"],
                })
            else:
                Extra.with_context(skip_tr_charge_sync=True).create(vals_to_set)

    # ---------------------------
    # Acción reporte
    # ---------------------------
    def action_print_technical_report(self):
        self.ensure_one()
        return self.env.ref(
            "estratego_maintenance_technical_report.action_report_maintenance_technical"
        ).report_action(self)
