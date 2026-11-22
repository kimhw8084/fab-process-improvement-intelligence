"""Portable bootstrap dispatch; production suite must use explicit product manifest routing."""
import importlib,json
from pathlib import Path
_BASE=Path(__file__).resolve().parent.parent
_product_id=json.loads((_BASE/'product.json').read_text(encoding='utf8'))['product_id']
_mod=importlib.import_module('products.'+_product_id+'.engine')
analyze=_mod.analyze

def __getattr__(name): return getattr(_mod,name)
