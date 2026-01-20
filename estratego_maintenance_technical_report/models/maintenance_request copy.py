# -*- coding: utf-8 -*-
from odoo import api, fields, models


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


    # Monto a cobrar al cliente (se muestra entre Evidencias y Conclusiones)
    technical_charge_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda",
        default=lambda self: self.env.company.currency_id.id,
    )
    technical_charge_amount = fields.Monetary(
        string="Monto a cobrar",
        currency_field="technical_charge_currency_id",
        default=0.0,
    )

    # Cierre
    technical_waiting_response_text = fields.Text(string="Mensaje / Cierre")
    technical_conclusions_html = fields.Html(string="Conclusiones", sanitize=False)


    def _needs_technical_sequence(self):
        """True si el correlativo está vacío o en '/'. """
        self.ensure_one()
        return not self.technical_report_number or self.technical_report_number in ("", "/")

    def _assign_technical_sequence_if_missing(self):
        """Asigna correlativo SOLO si falta."""
        for rec in self:
            if rec._needs_technical_sequence():
                rec.technical_report_number = self.env["ir.sequence"].sudo().next_by_code(
                    "maintenance.technical.report"
                ) or "N*PENDIENTE"


    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("technical_report_number") or vals.get("technical_report_number") == "/":
                vals["technical_report_number"] = seq.next_by_code("maintenance.technical.report") or "/"
        
        records = super().create(vals_list)

        records._sync_technical_charge_to_rental_line(trigger_fields={"create"})
        return records


    def write(self, vals):
        # Campos que deben disparar la sincronización
        charge_fields = {"technical_charge_amount", "technical_charge_currency_id", "technical_report_number"}
        must_sync_charge = bool(charge_fields.intersection(vals.keys()))

        res = super().write(vals)

        # ---------------------------
        # Correlativo para existentes
        # ---------------------------
        if not self.env.context.get("skip_tr_seq"):
            missing = self.filtered(lambda r: not r.technical_report_number or r.technical_report_number in ("", "/"))
            if missing:
                seq = self.env["ir.sequence"].sudo()
                for r in missing.sudo():
                    r.with_context(skip_tr_seq=True).write(
                        {"technical_report_number": seq.next_by_code("maintenance.technical.report") or "N*PENDIENTE"}
                    )
                must_sync_charge = True

        # ---------------------------
        # Sync cargo -> extra_commercial_service
        # ---------------------------
        if must_sync_charge and not self.env.context.get("skip_tr_charge"):
            self._sync_technical_charge_to_rental_line(trigger_fields=set(vals.keys()))

        return res

    

    def action_print_technical_report(self):
        self.ensure_one()
        return self.env.ref("estratego_maintenance_technical_report.action_report_maintenance_technical").report_action(self)

    # Helpers para el QWeb
    def _get_schedule_date_str(self):
        self.ensure_one()
        dt = self.schedule_date or fields.Datetime.now()
        # fecha en formato dd/mm/yyyy
        return dt.strftime("%d/%m/%Y")


    # ---------------------------------------------------------
    # Sync con vehicle.rental.line
    # ---------------------------------------------------------
    def _sync_technical_charge_to_rental_line(self, trigger_fields=None):
        """
        Crea/actualiza en vehicle.rental.line.extra_commercial_service_ids un registro
        ligado a este maintenance.request (vía maintenance_request_id).
        """
        trigger_fields = trigger_fields or set()

        # Si el modelo de rental no existe, no hacemos nada (evita crash si no está instalado).
        if "vehicle.rental.line" not in self.env:
            return

        Extra = self.env["vehicle.rental.extra.commercial.service"] if "vehicle.rental.extra.commercial.service" in self.env else None
        if not Extra:
            return

        for rec in self:
            # Requiere vínculo al rental line (en tu flujo se crea desde vehicle.rental.line.action_create_maintenance_request :contentReference[oaicite:1]{index=1})
            if "vehicle_rental_line_id" not in rec._fields:
                continue
            line = rec.vehicle_rental_line_id
            if not line:
                continue

            # 1) Sincroniza la moneda a nivel de rental line (si existe)
            if "service_commercial_currency_id" in line._fields and rec.technical_charge_currency_id:
                # Evitar recursiones raras si algún módulo reacciona al write del line
                line.with_context(skip_tr_charge=True).sudo().write(
                    {"service_commercial_currency_id": rec.technical_charge_currency_id.id}
                )

            # 2) Encuentra el extra comercial ligado a este informe
            extras = line.extra_commercial_service_ids
            if "maintenance_request_id" in Extra._fields:
                related = extras.filtered(lambda x: x.maintenance_request_id.id == rec.id)
            else:
                # Fallback ultra defensivo (si aún no actualizaron el otro modelo)
                related = self.env["vehicle.rental.extra.commercial.service"]

            description_value = (rec.technical_report_number or "").strip()
            amount_value = float(rec.technical_charge_amount or 0.0)

            # Valores a escribir/crear
            vals_to_set = {}
            if "description" in Extra._fields:
                vals_to_set["description"] = description_value
            if "amount" in Extra._fields:
                vals_to_set["amount"] = amount_value
            # Por si tu modelo maneja qty (en tu compute usan product_qty :contentReference[oaicite:2]{index=2})
            if "product_qty" in Extra._fields and "product_qty" not in vals_to_set:
                vals_to_set["product_qty"] = 1.0

            # Si el extra tiene moneda propia (no es seguro), setearla
            if "service_commercial_currency_id" in Extra._fields and rec.technical_charge_currency_id:
                vals_to_set["service_commercial_currency_id"] = rec.technical_charge_currency_id.id
            if "currency_id" in Extra._fields and rec.technical_charge_currency_id:
                vals_to_set["currency_id"] = rec.technical_charge_currency_id.id

            if related:
                # Si hay varios, actualizamos el primero (y opcionalmente podrías limpiar duplicados)
                related[:1].with_context(skip_tr_charge=True).sudo().write(vals_to_set)
            else:
                # Crear: usamos create sobre el O2M para que se complete vehicle_rental_line_id automáticamente
                create_vals = dict(vals_to_set)
                if "maintenance_request_id" in Extra._fields:
                    create_vals["maintenance_request_id"] = rec.id

                line.with_context(skip_tr_charge=True).sudo().extra_commercial_service_ids.create(create_vals)