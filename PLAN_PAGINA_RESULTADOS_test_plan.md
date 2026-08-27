# Test plan — página de resultados HTML

Generado por `/autoplan`, Fase 3 (Eng Review). Ver `PLAN_PAGINA_RESULTADOS.md`, sección
"Sección 3 — Test Review" para el razonamiento completo.

Archivo sugerido: `tests/test_html_report.py`.

| # | Test | Qué verifica |
|---|---|---|
| 1 | `test_escapes_player_names_with_html_chars` | Nombre sintético con `<`/`&` en el HTML de salida no rompe la estructura del documento (`html.escape()` aplicado) |
| 2 | `test_unicode_roundtrip` | Nombre con acentos (ej. "Étcheverry") escrito con `encoding="utf-8"` y leído de vuelta produce el string exacto, sin mojibake |
| 3 | `test_zero_probability_renders_as_percentage_not_dash` | `round_counts["CAMPEON"] == 0` renderiza `0.0%`, no `"—"` ni `NaN` (decisión #21: 0% es señal real, no dato faltante) |
| 4 | `test_html_ignores_top_n_shows_full_draw` | `counts` con más de 20 entradas → `render_probabilities_html` incluye el cuadro completo, sin cortar por `args.top` (decisión #20) |
| 5 | `test_backtest_html_skips_missing_model` | Modelo ausente de `report.models` → fila omitida, sin excepción (espeja `if r is None: continue` de `render_backtest`, decisión #22) |
| 6 | `test_generated_html_is_parseable` | Smoke test: el string de salida no lanza excepciones en `html.parser.HTMLParser` |
| 7 | `test_webbrowser_open_failure_does_not_propagate` | Mockear `webbrowser.open` para lanzar excepción → la función de render no propaga el error (el archivo ya se escribió) |
| 8 | `test_bar_percentage_rounds_cleanly` | Input con float "feo" (ej. `19.399999999999998`) → el string interpolado tiene 1 decimal, no ruido de punto flotante |
| 9 | `test_predictions_filename_convention` | `output/us_open_<año>_<modelo>.html` con año/modelo reales |
| 10 | `test_backtest_filename_convention` | `output/us_open_backtest_<inicio>-<fin>.html` con el rango real |
| 11 | `test_output_dir_created_if_missing` | `config.OUTPUT_DIR` no existe → se crea con `mkdir(parents=True, exist_ok=True)`, sin excepción |
