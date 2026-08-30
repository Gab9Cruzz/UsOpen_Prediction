"""Modo interactivo (`--serve`): servidor local mínimo, sin dependencias
nuevas (`http.server`/`json`/`threading` son stdlib), que sirve la página de
resultados y expone un endpoint para volver a simular sin reiniciar el
proceso (PLAN_PAGINA_RESULTADOS.md, revisión post-gate).

Solo escucha en 127.0.0.1 -- nunca en todas las interfaces. Es una
herramienta de un solo usuario corriendo en su propia máquina; no hay razón
para exponerla a la red.
"""

from __future__ import annotations

import json
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.cli import html_report
from src.cli.pipeline import run_prediction

VALID_MODELS = ("serve_return", "elo", "ensemble")

# Constante plana, sin interpolación (mismo criterio que PAGE_STYLE en
# html_report.py, decisión #27): evita el problema de tener que escapar
# cada `{`/`}` de JavaScript si se mezclara con f-string/`.format()`.
#
# El listener de submit se registra en `document` (delegación), no en el
# `<form>` -- el form se reemplaza enteramente en cada actualización
# (`#results.innerHTML = ...`), así que un listener atado al nodo viejo
# quedaría huérfano tras el primer click.
INTERACTIVE_SCRIPT = """
<script>
document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!form || form.id !== 'sim-form') return;
    ev.preventDefault();
    var status = document.getElementById('sim-status');
    var button = form.querySelector('button');
    var data = Object.fromEntries(new FormData(form).entries());
    button.disabled = true;
    if (status) {
        status.className = 'status';
        status.textContent = 'Simulando... puede tardar hasta un minuto.';
    }
    var controller = new AbortController();
    var timeoutId = setTimeout(function () { controller.abort(); }, 120000);
    fetch('/api/simulate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
        signal: controller.signal,
    }).then(function (resp) {
        return resp.json().then(function (payload) {
            return {ok: resp.ok, payload: payload};
        });
    }).then(function (result) {
        clearTimeout(timeoutId);
        if (result.ok) {
            document.getElementById('results').innerHTML = result.payload.html;
        } else {
            button.disabled = false;
            if (status) {
                status.className = 'status error';
                status.textContent = result.payload.error || 'Error simulando.';
            }
        }
    }).catch(function (err) {
        clearTimeout(timeoutId);
        button.disabled = false;
        if (status) {
            status.className = 'status error';
            status.textContent = (err && err.name === 'AbortError')
                ? 'La simulación tardó más de 2 minutos y se canceló. Probá con menos simulaciones.'
                : 'No se pudo conectar al servidor.';
        }
    });
});
</script>
"""

_SIM_LOCK = threading.Lock()


def _controls_form(simulations: int, model: str, draw_year: int) -> str:
    serve_sel = " selected" if model == "serve_return" else ""
    elo_sel = " selected" if model == "elo" else ""
    ensemble_sel = " selected" if model == "ensemble" else ""
    return (
        '<div class="controls"><form id="sim-form">'
        '<label>Simulaciones<input type="number" name="simulations" min="100" step="100" '
        f'value="{int(simulations)}"></label>'
        '<label>Modelo<select name="model">'
        f'<option value="serve_return"{serve_sel}>serve_return</option>'
        f'<option value="elo"{elo_sel}>elo</option>'
        f'<option value="ensemble"{ensemble_sel}>ensemble</option>'
        "</select></label>"
        '<label>Año del cuadro<input type="number" name="draw_year" '
        f'value="{int(draw_year)}"></label>'
        '<button type="submit">Simular de nuevo</button>'
        '<span class="status" id="sim-status"></span>'
        "</form></div>"
    )


def _results_html(state: dict) -> str:
    controls = _controls_form(state["simulations"], state["model"], state["draw_year"])
    return html_report.render_results_table(
        state["counts"], state["players_by_id"], state["simulations"],
        extra_content=controls, model=state["model"],
        known_results=state.get("meta", {}).get("known_results"),
        round_snapshots=state.get("meta", {}).get("round_snapshots"),
    )


class _Handler(BaseHTTPRequestHandler):
    # Estado compartido entre requests (protegido por _SIM_LOCK durante una
    # simulación): la última corrida, así el form y la tabla siempre
    # reflejan lo que se está mostrando. Se asigna en `run_server` antes de
    # levantar el server.
    state: dict = {}

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - firma fija de BaseHTTPRequestHandler
        pass  # silencia el log default de acceso a stderr por request

    def _send_html(self, body: str, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - nombre fijo de BaseHTTPRequestHandler
        if self.path != "/":
            self.send_error(404)
            return
        try:
            s = _Handler.state
            title = f"{s['meta']['tournament_name']} {s['meta']['tournament_year']} — en vivo"
            body = (
                html_report.render_masthead(s["meta"], s["simulations"])
                + f'<div id="results">{_results_html(s)}</div>'
                + INTERACTIVE_SCRIPT
            )
            self._send_html(html_report.render_page(title, body))
        except Exception as exc:  # noqa: BLE001 - nunca dejar la conexión colgada sin respuesta
            traceback.print_exc()
            self._send_html(f"<h1>Error armando la página</h1><p>{exc}</p>", status=500)

    def do_POST(self) -> None:  # noqa: N802 - nombre fijo de BaseHTTPRequestHandler
        if self.path != "/api/simulate":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
            simulations = int(body.get("simulations", _Handler.state["simulations"]))
            draw_year = int(body.get("draw_year", _Handler.state["draw_year"]))
            model = str(body.get("model", _Handler.state["model"]))
            if model not in VALID_MODELS:
                raise ValueError(f"modelo inválido: {model!r} (válidos: {', '.join(VALID_MODELS)})")
            if simulations < 1:
                raise ValueError("las simulaciones deben ser >= 1")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"Parámetros inválidos: {exc}"}, status=400)
            return

        with _SIM_LOCK:
            try:
                counts, players_by_id, meta = run_prediction(
                    draw_year=draw_year,
                    model=model,
                    simulations=simulations,
                    seed=_Handler.state["seed"],
                    exact_simulation=_Handler.state["exact_simulation"],
                    update_data=False,
                )
                _Handler.state.update(
                    simulations=simulations, draw_year=draw_year, model=model,
                    counts=counts, players_by_id=players_by_id, meta=meta,
                )
                # Arma el HTML de respuesta DENTRO del mismo try: si esto
                # falla (p.ej. el bracket) después de ya haber corrido la
                # simulación, antes se colaba sin capturar y el servidor
                # cortaba la conexión en seco -- el navegador lo mostraba
                # como "no responde" en vez de un error legible.
                html_payload = _results_html(_Handler.state)
            except Exception as exc:  # noqa: BLE001 - cualquier falla se reporta al form, nunca tira el server
                traceback.print_exc()  # visible en la terminal para diagnosticar
                self._send_json({"error": f"Error simulando: {exc}"}, status=500)
                return

        self._send_json({"html": html_payload})


def run_server(initial_args: dict) -> None:
    """Corre una simulación inicial con `initial_args` (mismos parámetros
    que ya acepta la CLI: draw_year/model/simulations/seed/exact_simulation),
    levanta el servidor en un puerto libre de 127.0.0.1, y bloquea hasta
    Ctrl+C."""
    counts, players_by_id, meta = run_prediction(
        draw_year=initial_args["draw_year"],
        model=initial_args["model"],
        simulations=initial_args["simulations"],
        seed=initial_args["seed"],
        exact_simulation=initial_args.get("exact_simulation", False),
        update_data=initial_args.get("update_data", False),
    )
    _Handler.state = {
        "simulations": initial_args["simulations"],
        "draw_year": initial_args["draw_year"],
        "model": initial_args["model"],
        "seed": initial_args["seed"],
        "exact_simulation": initial_args.get("exact_simulation", False),
        "counts": counts,
        "players_by_id": players_by_id,
        "meta": meta,
    }

    # Puerto 0: el SO asigna uno libre (PLAN_PAGINA_RESULTADOS.md, revisión
    # post-gate) -- evita el failure mode de un puerto fijo ya ocupado.
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    host, port = httpd.server_address
    url = f"http://{host}:{port}/"
    print(f"Servidor interactivo en {url}  (Ctrl+C para detener)")

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        httpd.server_close()
