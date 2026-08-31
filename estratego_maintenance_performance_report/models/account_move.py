# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import ValidationError


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.constrains(
        "rental_extra_service_id",
        "rental_extra_commercial_service_id",
        "move_id",
    )
    def _check_rental_extra_unique_active(self):
        """Mantiene unicidad en facturas, permitiendo trazabilidad en NC.

        El módulo de alquiler impide que un Extra esté en dos facturas cliente
        activas. Una nota de crédito no es una segunda facturación: es la reversión
        de la primera y debe conservar el vínculo para poder calcular venta neta.
        """
        for line in self:
            move = line.move_id
            if not move or move.state == "cancel":
                continue

            # Las NC pueden conservar el vínculo con el Extra de la factura origen.
            if move.move_type == "out_refund":
                continue

            if move.move_type not in ("out_invoice", "out_receipt"):
                continue

            for field_name, label in (
                ("rental_extra_service_id", _("Extra Operaciones")),
                ("rental_extra_commercial_service_id", _("Extra Comercial")),
            ):
                source = line[field_name]
                if not source:
                    continue
                duplicate = self.sudo().search([
                    ("id", "!=", line.id),
                    (field_name, "=", source.id),
                    ("move_id.state", "!=", "cancel"),
                    ("move_id.move_type", "in", ("out_invoice", "out_receipt")),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "%s ya está relacionado con otra factura activa: %s."
                    ) % (label, duplicate.move_id.display_name))


class AccountMove(models.Model):
    _inherit = "account.move"

    def _reverse_moves(self, default_values_list=None, cancel=False):
        """Conserva Extra -> línea de factura también en notas de crédito.

        ``rental_extra_service_id`` tiene ``copy=False`` por diseño, por lo que la
        reversión estándar no lo copia. Después de crear la NC se repone el vínculo
        usando la posición de las líneas comerciales; si la estructura difiere, se
        usa una coincidencia conservadora por secuencia/producto/descripción.
        """
        reverse_moves = super()._reverse_moves(
            default_values_list=default_values_list,
            cancel=cancel,
        )
        self._link_rental_extras_to_reversals(reverse_moves)
        return reverse_moves

    def _link_rental_extras_to_reversals(self, reverse_moves):
        for reverse in reverse_moves.filtered(
            lambda move: move.move_type == "out_refund" and move.reversed_entry_id
        ):
            source = reverse.reversed_entry_id
            source_lines = source.invoice_line_ids.filtered(
                lambda line: line.display_type == "product"
            ).sorted(key=lambda line: (line.sequence, line.id))
            reverse_lines = reverse.invoice_line_ids.filtered(
                lambda line: line.display_type == "product"
            ).sorted(key=lambda line: (line.sequence, line.id))

            # La reversión estándar conserva estructura y orden de invoice_line_ids.
            # Este camino evita inferencias por importe.
            if len(source_lines) == len(reverse_lines):
                pairs = zip(source_lines, reverse_lines)
            else:
                pairs = []
                remaining = reverse_lines
                for source_line in source_lines:
                    candidates = remaining.filtered(
                        lambda line: (
                            line.sequence == source_line.sequence
                            and line.product_id == source_line.product_id
                            and line.name == source_line.name
                        )
                    )
                    if len(candidates) != 1:
                        candidates = remaining.filtered(
                            lambda line: (
                                line.product_id == source_line.product_id
                                and line.name == source_line.name
                            )
                        )
                    if len(candidates) == 1:
                        target = candidates[0]
                        pairs.append((source_line, target))
                        remaining -= target

            for source_line, reverse_line in pairs:
                vals = {}
                if source_line.rental_extra_service_id:
                    vals["rental_extra_service_id"] = source_line.rental_extra_service_id.id
                if source_line.rental_extra_commercial_service_id:
                    vals["rental_extra_commercial_service_id"] = source_line.rental_extra_commercial_service_id.id
                if vals:
                    reverse_line.sudo().write(vals)
