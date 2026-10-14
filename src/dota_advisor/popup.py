from __future__ import annotations

import argparse
import json
import queue
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class PopupRecommendation:
    target_name: str
    purchase_name: str
    availability: str


def format_recommendation(payload: dict[str, Any]) -> PopupRecommendation:
    additional_gold = max(0, int(payload.get("additional_gold_required") or 0))
    target_name = str(payload.get("item_name") or "Unknown item")
    purchase_name = str(payload.get("next_component") or target_name)
    return PopupRecommendation(
        target_name=target_name,
        purchase_name=purchase_name,
        availability=f"need {additional_gold}g" if additional_gold else "buy now",
    )


def _format_game_time(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _format_updated_at(value: str | None) -> str:
    if not value:
        return "Not updated"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "Updated"
    return f"Updated {parsed.astimezone().strftime('%H:%M:%S')}"


class ApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, path: str, method: str = "GET") -> Any:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=b"" if method == "POST" else None,
            headers={"Accept": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
                detail = body.get("detail", str(exc))
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = str(exc)
            raise RuntimeError(str(detail)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Cannot reach AegisLens at {self.base_url}. Start the server first."
            ) from exc

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._request("/api/v1/state"),
            "recommendations": self._request("/api/v1/recommendations/latest"),
            "capture": self._request("/api/v1/capture/status"),
        }

    def refresh_recommendations(self) -> dict[str, Any]:
        self._request("/api/v1/recommendations", method="POST")
        return self.snapshot()


class CompanionWindow:
    BACKGROUND = "#091016"
    PANEL = "#14212b"
    PANEL_FIRST = "#192a35"
    BORDER = "#2b3c48"
    TEXT = "#edf3f7"
    MUTED = "#91a2ae"
    ACCENT = "#f1a44b"
    GOOD = "#79d39f"
    ERROR = "#ffc1ba"

    def __init__(
        self,
        root: tk.Tk,
        api_client: ApiClient,
        *,
        poll_seconds: float,
        always_on_top: bool,
    ) -> None:
        self.root = root
        self.api_client = api_client
        self.poll_ms = max(500, round(poll_seconds * 1000))
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aegislens-popup")
        self._results: queue.Queue[Future[dict[str, Any]]] = queue.Queue()
        self._busy = False
        self._closed = False
        self._card_frames: list[tk.Frame] = []
        self._card_values: list[dict[str, tk.StringVar]] = []

        self._configure_window(always_on_top)
        self._build_interface(always_on_top)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(50, self._drain_results)
        self.root.after(100, self._poll)

    def _configure_window(self, always_on_top: bool) -> None:
        width, height = 330, 370
        screen_width = self.root.winfo_screenwidth()
        x_position = max(0, screen_width - width - 24)
        self.root.title("AegisLens Companion")
        self.root.geometry(f"{width}x{height}+{x_position}+48")
        self.root.minsize(300, 330)
        self.root.configure(bg=self.BACKGROUND)
        self.root.attributes("-topmost", always_on_top)
        self.root.lift()

    def _build_interface(self, always_on_top: bool) -> None:
        header = tk.Frame(self.root, bg=self.BACKGROUND, padx=10, pady=8)
        header.pack(fill="x")
        title_group = tk.Frame(header, bg=self.BACKGROUND)
        title_group.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_group,
            text="AEGISLENS",
            bg=self.BACKGROUND,
            fg=self.ACCENT,
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_group,
            text="Next purchases",
            bg=self.BACKGROUND,
            fg=self.TEXT,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        self.connection = tk.StringVar(value="Connecting…")
        self.connection_label = tk.Label(
            header,
            textvariable=self.connection,
            bg="#492327",
            fg=self.ERROR,
            padx=7,
            pady=3,
            font=("Segoe UI", 8, "bold"),
        )
        self.connection_label.pack(side="right")

        self.state_text = tk.StringVar(value="Waiting for match context…")
        tk.Label(
            self.root,
            textvariable=self.state_text,
            bg="#0d171f",
            fg="#aebdc7",
            padx=10,
            pady=5,
            anchor="w",
            font=("Segoe UI", 9),
        ).pack(fill="x")

        self.message = tk.StringVar(value="")
        self.message_label = tk.Label(
            self.root,
            textvariable=self.message,
            bg="#392b1a",
            fg="#ffe0ad",
            padx=10,
            pady=7,
            anchor="w",
            justify="left",
            wraplength=300,
            font=("Segoe UI", 8),
        )

        self.cards = tk.Frame(self.root, bg=self.BACKGROUND, padx=8, pady=6)
        self.cards.pack(fill="both", expand=True)
        self.empty_text = tk.StringVar(
            value="Save match context in the dashboard to receive recommendations."
        )
        self.empty_label = tk.Label(
            self.cards,
            textvariable=self.empty_text,
            bg=self.BACKGROUND,
            fg=self.MUTED,
            justify="center",
            wraplength=280,
            font=("Segoe UI", 9),
        )
        self.empty_label.pack(fill="both", expand=True, padx=15, pady=20)
        for index in range(3):
            self._create_card(index)

        footer = tk.Frame(self.root, bg="#0b141b", padx=8, pady=6)
        footer.pack(fill="x", side="bottom")
        status_row = tk.Frame(footer, bg="#0b141b")
        status_row.pack(fill="x")
        self.capture_text = tk.StringVar(value="Capture stopped")
        self.updated_text = tk.StringVar(value="Not updated")
        tk.Label(
            status_row,
            textvariable=self.capture_text,
            bg="#0b141b",
            fg=self.MUTED,
            font=("Segoe UI", 8),
        ).pack(side="left")
        tk.Label(
            status_row,
            textvariable=self.updated_text,
            bg="#0b141b",
            fg=self.MUTED,
            font=("Segoe UI", 8),
        ).pack(side="right")

        button_row = tk.Frame(footer, bg="#0b141b", pady=5)
        button_row.pack(fill="x")
        self._button(button_row, "Refresh advice", self.refresh).pack(
            side="left", fill="x", expand=True, padx=(0, 4)
        )
        self._button(button_row, "Dashboard", self.open_dashboard).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )
        self.topmost = tk.BooleanVar(value=always_on_top)
        tk.Checkbutton(
            footer,
            text="Always on top",
            variable=self.topmost,
            command=self._toggle_topmost,
            bg="#0b141b",
            activebackground="#0b141b",
            fg=self.MUTED,
            activeforeground=self.TEXT,
            selectcolor=self.PANEL,
            font=("Segoe UI", 8),
        ).pack(anchor="w")

    def _button(self, parent: tk.Widget, text: str, command: Any) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg="#172630",
            activebackground="#223945",
            fg=self.TEXT,
            activeforeground=self.TEXT,
            relief="flat",
            padx=6,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )

    def _create_card(self, index: int) -> None:
        background = self.PANEL_FIRST if index == 0 else self.PANEL
        frame = tk.Frame(
            self.cards,
            bg=background,
            highlightbackground=self.ACCENT if index == 0 else self.BORDER,
            highlightthickness=1,
            padx=8,
            pady=6,
        )
        variables = {
            "purchase": tk.StringVar(),
            "target": tk.StringVar(),
        }
        tk.Label(
            frame,
            text=f"#{index + 1}",
            bg=background,
            fg=self.ACCENT,
            font=("Segoe UI", 10, "bold"),
            width=3,
        ).pack(side="left")
        details = tk.Frame(frame, bg=background)
        details.pack(side="left", fill="x", expand=True)
        tk.Label(
            details,
            textvariable=variables["purchase"],
            bg=background,
            fg=self.TEXT,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        ).pack(fill="x")
        tk.Label(
            details,
            textvariable=variables["target"],
            bg=background,
            fg=self.MUTED,
            anchor="w",
            font=("Segoe UI", 8),
        ).pack(fill="x")
        self._card_frames.append(frame)
        self._card_values.append(variables)

    def _submit(self, function: Any) -> None:
        if self._busy or self._closed:
            return
        self._busy = True
        future = self._executor.submit(function)
        future.add_done_callback(self._results.put)

    def _poll(self) -> None:
        if self._closed:
            return
        self._submit(self.api_client.snapshot)
        self.root.after(self.poll_ms, self._poll)

    def _drain_results(self) -> None:
        if self._closed:
            return
        try:
            while True:
                future = self._results.get_nowait()
                self._busy = False
                try:
                    snapshot = future.result()
                except Exception as exc:
                    self._show_error(str(exc))
                else:
                    self._render(snapshot)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_results)

    def _show_error(self, message: str) -> None:
        self.connection.set("Offline")
        self.connection_label.configure(bg="#492327", fg=self.ERROR)
        self.message.set(message)
        if not self.message_label.winfo_ismapped():
            self.message_label.pack(fill="x", padx=10, pady=(7, 0), before=self.cards)

    def _render(self, snapshot: dict[str, Any]) -> None:
        self.connection.set("Live")
        self.connection_label.configure(bg="#173b2a", fg="#98e8bb")
        state = snapshot.get("state")
        if state:
            role = str(state.get("role") or "").replace("_", " ")
            confidence = round(float(state.get("extraction_confidence") or 0) * 100)
            self.state_text.set(
                f"{state.get('hero') or 'Unknown hero'} · {role} · {state.get('gold', 0)} gold · "
                f"{_format_game_time(int(state.get('game_time_seconds') or 0))} · "
                f"{confidence}% confidence"
            )
        else:
            self.state_text.set("Waiting for match context…")

        capture = snapshot.get("capture") or {}
        running = bool(capture.get("running"))
        analysis_count = int(capture.get("analysis_count") or 0)
        self.capture_text.set(
            f"Capture active · {analysis_count} analyzed" if running else "Capture stopped"
        )
        capture_error = capture.get("last_error")
        analysis_warnings = capture.get("last_analysis_warnings") or []
        if capture_error or analysis_warnings:
            self.message.set(str(capture_error or analysis_warnings[0]))
            if not self.message_label.winfo_ismapped():
                self.message_label.pack(fill="x", padx=10, pady=(7, 0), before=self.cards)
        else:
            self.message.set("")
            self.message_label.pack_forget()

        recommendations = snapshot.get("recommendations") or []
        self._render_recommendations(recommendations)

    def _render_recommendations(self, recommendations: list[dict[str, Any]]) -> None:
        if not recommendations:
            for frame in self._card_frames:
                frame.pack_forget()
            if not self.empty_label.winfo_ismapped():
                self.empty_label.pack(fill="both", expand=True, padx=15, pady=20)
            self.updated_text.set("Not updated")
            return

        self.empty_label.pack_forget()
        for index, (frame, values) in enumerate(
            zip(self._card_frames, self._card_values, strict=False)
        ):
            if index >= len(recommendations):
                frame.pack_forget()
                continue
            recommendation = format_recommendation(recommendations[index])
            values["purchase"].set(recommendation.purchase_name)
            target = (
                f"for {recommendation.target_name} · {recommendation.availability}"
                if recommendation.purchase_name != recommendation.target_name
                else recommendation.availability
            )
            values["target"].set(target)
            if not frame.winfo_ismapped():
                frame.pack(fill="x", pady=(0, 7))
        self.updated_text.set(_format_updated_at(recommendations[0].get("generated_at")))

    def refresh(self) -> None:
        self.connection.set("Refreshing…")
        self._submit(self.api_client.refresh_recommendations)

    def open_dashboard(self) -> None:
        webbrowser.open(f"{self.api_client.base_url}/")

    def _toggle_topmost(self) -> None:
        self.root.attributes("-topmost", self.topmost.get())
        if self.topmost.get():
            self.root.lift()

    def close(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def launch_popup(
    *,
    api_url: str = "http://127.0.0.1:8000",
    poll_seconds: float = 2.0,
    always_on_top: bool = True,
) -> None:
    if poll_seconds < 0.5:
        raise ValueError("Popup polling interval must be at least 0.5 seconds.")
    root = tk.Tk()
    CompanionWindow(
        root,
        ApiClient(api_url),
        poll_seconds=poll_seconds,
        always_on_top=always_on_top,
    )
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="AegisLens always-on-top companion")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--no-topmost", action="store_true")
    args = parser.parse_args()
    launch_popup(
        api_url=args.api_url,
        poll_seconds=args.poll_seconds,
        always_on_top=not args.no_topmost,
    )


if __name__ == "__main__":
    main()
