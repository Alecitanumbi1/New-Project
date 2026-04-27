# Conciliador de cuentas multiusuario

Este proyecto implementa un **conciliador de cuentas** para:

- Banco vs libros contables.
- Cuenta contable vs cuenta contable.
- Múltiples usuarios y múltiples empresas (tenants).

Está pensado como base funcional en SQLite + Python estándar (sin dependencias externas).

## Funcionalidades

- Gestión de empresas (tenants).
- Gestión de usuarios y asignación por tenant.
- Cuentas por tenant (`bank` o `ledger`).
- Carga de movimientos.
- Sugerencias de conciliación por:
  - Mismo monto (cuenta vs cuenta), o
  - Monto opuesto (banco vs libro).
- Confirmación manual de conciliaciones.
- Listado de movimientos no conciliados.

## Uso rápido

```bash
python3 reconciliador.py --db demo.db init-db
python3 reconciliador.py --db demo.db add-tenant "Mi Empresa"
python3 reconciliador.py --db demo.db add-user admin@empresa.com "Admin"
python3 reconciliador.py --db demo.db assign-user 1 1 --role admin
python3 reconciliador.py --db demo.db add-account 1 "Banco Principal" bank
python3 reconciliador.py --db demo.db add-account 1 "Caja General" ledger
python3 reconciliador.py --db demo.db add-txn 1 1 2026-04-20 -1200 --reference TRX-100
python3 reconciliador.py --db demo.db add-txn 1 2 2026-04-21 1200 --reference ASI-55
python3 reconciliador.py --db demo.db suggest 1 1 2 --days 3
python3 reconciliador.py --db demo.db confirm 1 1 2 --note "Conciliado abril"
```

## Notas

- Los IDs son autoincrementales.
- `txn_date` usa formato ISO (`YYYY-MM-DD`).
- Puedes adaptar reglas de sugerencia para tolerancias más complejas (comisiones, redondeos, etc.).
