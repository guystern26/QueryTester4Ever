# -*- coding: utf-8 -*-
"""
generators — individual field value generator implementations.

Each module exposes:
  - generate(rule, index, prepared=None) -> str  — called per event
  - prepare(rule) -> Any  — called once per rule before the generation loop

The GENERATOR_REGISTRY maps generation_type strings to generate functions.
The PREPARE_REGISTRY maps generation_type strings to prepare functions.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from core.models import GeneratorRule
from generators.numbered import generate as gen_numbered, prepare as prep_numbered
from generators.pick_list import generate as gen_pick_list, prepare as prep_pick_list
from generators.random_number import generate as gen_random_number, prepare as prep_random_number
from generators.unique_id import generate as gen_unique_id, prepare as prep_unique_id
from generators.email import generate as gen_email, prepare as prep_email
from generators.ip_address import generate as gen_ip_address, prepare as prep_ip_address
from generators.general_field import generate as gen_general_field, prepare as prep_general_field


GeneratorFn = Callable[..., str]
PrepareFn = Callable[[GeneratorRule], Any]

GENERATOR_REGISTRY: Dict[str, GeneratorFn] = {
    "numbered": gen_numbered,
    "pick_list": gen_pick_list,
    "random_number": gen_random_number,
    "unique_id": gen_unique_id,
    "email": gen_email,
    "ip_address": gen_ip_address,
    "general_field": gen_general_field,
}

PREPARE_REGISTRY: Dict[str, PrepareFn] = {
    "numbered": prep_numbered,
    "pick_list": prep_pick_list,
    "random_number": prep_random_number,
    "unique_id": prep_unique_id,
    "email": prep_email,
    "ip_address": prep_ip_address,
    "general_field": prep_general_field,
}
