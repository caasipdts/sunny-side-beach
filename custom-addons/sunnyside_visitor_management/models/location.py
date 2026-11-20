# -*- coding: utf-8 -*-
from odoo import fields, models


class SunnysideLocation(models.Model):
    _name = 'sunnyside.location'
    _description = 'Sunnyside Location / Neighbourhood'
    _order = 'name asc'

    name = fields.Char(
        string='Neighbourhood Name',
        required=True,
        translate=True,
        index='trigram',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    description = fields.Text(
        string='Description',
    )
