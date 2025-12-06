#!/usr/bin/env python3
"""
Orbital Mechanics Dashboard (Tkinter + Matplotlib)

Features:
- Fetches heliocentric positions of planets from NASA JPL Horizons.
- Toggles to show/hide individual planets.
- Date and time controls (UTC).
- Asteroid overlay: enter an asteroid name or ID (e.g., Apophis, 99942).
- Embedded matplotlib plot inside a Tkinter GUI.
- Zoom in/out & reset zoom controls.
- Dark mode UI with styled buttons.
"""

import datetime as dt
import re
import tkinter as tk
from tkinter import ttk, messagebox

import requests
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.transforms as mtransforms  # <--- added

# ---------------------------
# Horizons API helpers
# ---------------------------

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"

# NAIF IDs for planetary centers (not barycenters)
PLANETS = {
    "Mercury": "199",
    "Venus": "299",
    "Earth": "399",
    "Mars": "499",
    "Jupiter": "599",
    "Saturn": "699",
    "Uranus": "799",
    "Neptune": "899",
}


def horizons_state_vectors(command: str, when: dt.datetime):
    """
    Query JPL Horizons for heliocentric Cartesian coordinates (X, Y, Z)
    of a given object (planet or asteroid).

    `command` can be:
      - NAIF ID like '399'
      - Name / designation like 'Apophis' or 'Ceres'

    Returns:
        (x_au, y_au, z_au) in astronomical units.
    """
    start_time = when.strftime("%Y-%m-%d")
    stop_time = (when + dt.timedelta(days=1)).strftime("%Y-%m-%d")

    params = {
        "format": "json",
        "COMMAND": command,
        "CENTER": "@sun",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "VECTORS",
        "START_TIME": start_time,
        "STOP_TIME": stop_time,
        "STEP_SIZE": "1d",
        "OUT_UNITS": "AU-D",
    }

    resp = requests.get(HORIZONS_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"Horizons error for {command}: {data['error']}")

    result_text = data.get("result", "")
    if not result_text:
        raise RuntimeError(f"No 'result' field in Horizons response for {command}")

    return _parse_xyz_from_horizons_result(result_text)


def _parse_xyz_from_horizons_result(result_text: str):
    """
    Parse the first state vector (X, Y, Z) from Horizons `result` text.

    Looks for the block between $$SOE and $$EOE, then the line like:
        X = ... Y = ... Z = ...
    """
    m = re.search(r"\$\$SOE(.*?)\$\$EOE", result_text, re.S)
    if not m:
        raise RuntimeError("Could not find $$SOE/$$EOE block in Horizons result")

    block = m.group(1)

    xyz_line = None
    for line in block.splitlines():
        if "X =" in line and "Y =" in line and "Z =" in line:
            xyz_line = line.strip()
            break

    if xyz_line is None:
        raise RuntimeError("Could not find X/Y/Z line in Horizons result block")

    # Match scientific-notation floats like -1.234567890E+00
    nums = re.findall(r"([-+]?\d+\.\d+E[+-]?\d+)", xyz_line)
    if len(nums) < 3:
        raise RuntimeError(f"Could not parse X/Y/Z from line: {xyz_line}")

    x_au = float(nums[0])
    y_au = float(nums[1])
    z_au = float(nums[2])
    return x_au, y_au, z_au


# ---------------------------
# Tkinter GUI application
# ---------------------------

class OrbitDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Orbital Mechanics Dashboard")
        self.geometry("1100x700")

        # Dark mode colors
        self.bg_color = "#050509"
        self.panel_bg = "#10101a"
        self.fg_color = "#e0e0e0"
        self.muted_fg = "#a0a0b0"
        self.accent = "#6c5ce7"
        self.accent_hover = "#8e8af0"

        self.configure(bg=self.bg_color)

        # ttk style
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.style.configure("Root.TFrame", background=self.bg_color)
        self.style.configure("Dark.TFrame", background=self.panel_bg)

        self.style.configure("Dark.TLabel", background=self.panel_bg, foreground=self.fg_color)
        self.style.configure("Status.TLabel", background=self.panel_bg, foreground=self.muted_fg)

        self.style.configure("Dark.TCheckbutton", background=self.panel_bg, foreground=self.fg_color)

        self.style.configure(
            "Dark.TEntry",
            fieldbackground="#181824",
            foreground=self.fg_color,
            insertcolor=self.fg_color,
        )

        # Buttons
        self.style.configure(
            "Accent.TButton",
            background=self.accent,
            foreground="#ffffff",
            padding=(10, 4),
            relief="flat",
            borderwidth=0,
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", self.accent_hover)],
            foreground=[("disabled", "#666666")],
        )

        self.style.configure(
            "ZoomGreen.TButton",
            background="#2ecc71",
            foreground="#ffffff",
            padding=(8, 3),
            relief="flat",
            borderwidth=0,
        )
        self.style.map(
            "ZoomGreen.TButton",
            background=[("active", "#51f18f")],
        )

        self.style.configure(
            "ZoomOrange.TButton",
            background="#e67e22",
            foreground="#ffffff",
            padding=(8, 3),
            relief="flat",
            borderwidth=0,
        )
        self.style.map(
            "ZoomOrange.TButton",
            background=[("active", "#f39c45")],
        )

        self.style.configure(
            "ZoomBlue.TButton",
            background="#3498db",
            foreground="#ffffff",
            padding=(8, 3),
            relief="flat",
            borderwidth=0,
        )
        self.style.map(
            "ZoomBlue.TButton",
            background=[("active", "#5dade2")],
        )

        # State
        self.planet_vars = {}
        self.show_asteroid_var = tk.BooleanVar(value=False)
        self.asteroid_name_var = tk.StringVar(value="Apophis")
        self.date_var = tk.StringVar()
        self.time_var = tk.StringVar()

        # Zoom & cached plot data
        self.zoom_factor = 1.0
        self.last_positions = {}
        self.last_when = None
        self.last_asteroid_label = None
        self.last_asteroid_pos = None

        self._init_datetime_defaults()
        self._build_ui()
        self._init_plot()

        # Initial fetch
        self.refresh_data()

    # ----- UI setup -----

    def _init_datetime_defaults(self):
        now = dt.datetime.now(dt.UTC)
        self.date_var.set(now.strftime("%Y-%m-%d"))
        self.time_var.set(now.strftime("%H:%M"))

    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        root_frame = ttk.Frame(self, padding=0, style="Root.TFrame")
        root_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        root_frame.columnconfigure(1, weight=1)
        root_frame.rowconfigure(0, weight=1)

        control_frame = ttk.Frame(root_frame, padding=10, style="Dark.TFrame")
        control_frame.grid(row=0, column=0, sticky="nsw")

        plot_frame = ttk.Frame(root_frame, padding=10, style="Dark.TFrame")
        plot_frame.grid(row=0, column=1, sticky="nsew")
        plot_frame.rowconfigure(0, weight=1)
        plot_frame.columnconfigure(0, weight=1)
        self.plot_frame = plot_frame

        # --- Date/Time ---
        ttk.Label(
            control_frame,
            text="Date / Time (UTC)",
            font=("TkDefaultFont", 10, "bold"),
            style="Dark.TLabel",
        ).grid(row=0, column=0, columnspan=2, pady=(0, 5), sticky="w")

        ttk.Label(control_frame, text="Date (YYYY-MM-DD):", style="Dark.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Entry(control_frame, textvariable=self.date_var, width=14, style="Dark.TEntry").grid(
            row=1, column=1, sticky="w", pady=2
        )

        ttk.Label(control_frame, text="Time (HH:MM):", style="Dark.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(control_frame, textvariable=self.time_var, width=14, style="Dark.TEntry").grid(
            row=2, column=1, sticky="w", pady=2
        )

        ttk.Button(
            control_frame,
            text="Now (UTC)",
            command=self.set_now,
            style="Accent.TButton",
        ).grid(row=3, column=0, columnspan=2, pady=(6, 12), sticky="we")

        # --- Planets ---
        ttk.Label(
            control_frame,
            text="Planets",
            font=("TkDefaultFont", 10, "bold"),
            style="Dark.TLabel",
        ).grid(row=4, column=0, columnspan=2, pady=(0, 5), sticky="w")

        row = 5
        for name in PLANETS.keys():
            var = tk.BooleanVar(value=True if name in ("Mercury", "Venus", "Earth", "Mars") else False)
            self.planet_vars[name] = var
            ttk.Checkbutton(
                control_frame,
                text=name,
                variable=var,
                style="Dark.TCheckbutton",
            ).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1

        # --- Asteroid overlay ---
        ttk.Label(
            control_frame,
            text="Asteroid Overlay",
            font=("TkDefaultFont", 10, "bold"),
            style="Dark.TLabel",
        ).grid(row=row, column=0, columnspan=2, pady=(10, 5), sticky="w")
        row += 1

        ttk.Checkbutton(
            control_frame,
            text="Show asteroid",
            variable=self.show_asteroid_var,
            style="Dark.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Label(control_frame, text="Name or ID:", style="Dark.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Entry(control_frame, textvariable=self.asteroid_name_var, width=18, style="Dark.TEntry").grid(
            row=row, column=1, sticky="w"
        )
        row += 1

        ttk.Label(
            control_frame,
            text="Examples:\n  Apophis\n  99942\n  Ceres\n  Bennu",
            justify="left",
            style="Dark.TLabel",
            foreground=self.muted_fg,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 10))
        row += 1

        # --- Refresh ---
        ttk.Button(
            control_frame,
            text="Refresh",
            command=self.refresh_data,
            style="Accent.TButton",
        ).grid(row=row, column=0, columnspan=2, sticky="we", pady=(8, 0))
        row += 1

        # --- Zoom ---
        ttk.Label(
            control_frame,
            text="Zoom",
            font=("TkDefaultFont", 10, "bold"),
            style="Dark.TLabel",
        ).grid(row=row, column=0, columnspan=2, pady=(12, 4), sticky="w")
        row += 1

        zoom_frame = ttk.Frame(control_frame, style="Dark.TFrame")
        zoom_frame.grid(row=row, column=0, columnspan=2, sticky="we")
        zoom_frame.columnconfigure(0, weight=1)
        zoom_frame.columnconfigure(1, weight=1)
        zoom_frame.columnconfigure(2, weight=1)

        ttk.Button(
            zoom_frame,
            text="In",
            command=self.zoom_in,
            style="ZoomGreen.TButton",
        ).grid(row=0, column=0, padx=(0, 4), sticky="we")

        ttk.Button(
            zoom_frame,
            text="Out",
            command=self.zoom_out,
            style="ZoomOrange.TButton",
        ).grid(row=0, column=1, padx=(0, 4), sticky="we")

        ttk.Button(
            zoom_frame,
            text="Reset",
            command=self.reset_zoom,
            style="ZoomBlue.TButton",
        ).grid(row=0, column=2, sticky="we")
        row += 1

        # Status
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(
            control_frame,
            textvariable=self.status_var,
            style="Status.TLabel",
            wraplength=200,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _init_plot(self):
        self.fig = Figure(figsize=(6, 6), dpi=100)
        self.fig.patch.set_facecolor(self.bg_color)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor(self.panel_bg)
        self.ax.set_xlabel("X (AU)", color=self.fg_color)
        self.ax.set_ylabel("Y (AU)", color=self.fg_color)
        self.ax.tick_params(colors=self.muted_fg)
        for spine in self.ax.spines.values():
            spine.set_color("#444444")
        self.ax.set_aspect("equal", "box")

        canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        widget = canvas.get_tk_widget()
        widget.configure(bg=self.panel_bg, highlightthickness=0, bd=0)
        widget.grid(row=0, column=0, sticky="nsew")
        self.canvas = canvas

    # ----- UI actions -----

    def set_now(self):
        now = dt.datetime.now(dt.UTC)
        self.date_var.set(now.strftime("%Y-%m-%d"))
        self.time_var.set(now.strftime("%H:%M"))
        self.status_var.set("Date/time set to current UTC.")

    def _get_datetime(self):
        date_str = self.date_var.get().strip()
        time_str = self.time_var.get().strip() or "00:00"
        try:
            when = dt.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError("Invalid date/time format. Use YYYY-MM-DD and HH:MM.")
        return when

    def refresh_data(self):
        try:
            when = self._get_datetime()
        except ValueError as e:
            messagebox.showerror("Invalid Date/Time", str(e))
            return

        self.status_var.set("Fetching data from Horizons...")
        self.update_idletasks()

        positions = {}
        errors = []

        for name, naif_id in PLANETS.items():
            if not self.planet_vars[name].get():
                continue
            try:
                x, y, z = horizons_state_vectors(naif_id, when)
                positions[name] = (x, y, z)
            except Exception as e:
                errors.append(f"{name}: {e}")

        asteroid_label = None
        asteroid_pos = None
        if self.show_asteroid_var.get():
            raw_name = self.asteroid_name_var.get().strip()
            if raw_name:
                try:
                    x, y, z = horizons_state_vectors(raw_name, when)
                    asteroid_label = raw_name
                    asteroid_pos = (x, y, z)
                except Exception as e:
                    errors.append(f"Asteroid ({raw_name}): {e}")

        self.last_positions = positions
        self.last_when = when
        self.last_asteroid_label = asteroid_label
        self.last_asteroid_pos = asteroid_pos

        self.update_plot(positions, when, asteroid_label, asteroid_pos)

        if errors:
            self.status_var.set("Completed with errors:\n" + "\n".join(errors))
        else:
            self.status_var.set("Data updated successfully.")

    # ----- Zoom helpers -----

    def _redraw_from_cache(self):
        if self.last_when is None:
            self.status_var.set("Nothing to zoom yet. Fetch data first.")
            return
        self.update_plot(
            self.last_positions,
            self.last_when,
            self.last_asteroid_label,
            self.last_asteroid_pos,
        )

    def zoom_in(self):
        self.zoom_factor *= 1.25
        self._redraw_from_cache()

    def zoom_out(self):
        self.zoom_factor /= 1.25
        if self.zoom_factor < 0.1:
            self.zoom_factor = 0.1
        self._redraw_from_cache()

    def reset_zoom(self):
        self.zoom_factor = 1.0
        self._redraw_from_cache()

    # ----- Plotting -----

    def update_plot(self, positions, when, asteroid_label=None, asteroid_pos=None):
        self.ax.clear()
        self.ax.set_facecolor(self.panel_bg)

        xs, ys = [], []

        orbit_radii = {
            "Mercury": 0.39,
            "Venus": 0.72,
            "Earth": 1.00,
            "Mars": 1.52,
            "Jupiter": 5.20,
            "Saturn": 9.58,
            "Uranus": 19.20,
            "Neptune": 30.05,
        }

        # planet label transform: 6pt to the right of marker
        planet_label_transform = mtransforms.offset_copy(
            self.ax.transData, fig=self.fig, x=6, y=0, units="points"
        )
        # asteroid label transform: a bit farther
        asteroid_label_transform = mtransforms.offset_copy(
            self.ax.transData, fig=self.fig, x=8, y=0, units="points"
        )

        self.ax.scatter(
            0,
            0,
            s=120,
            marker="o",
            color="#ffd54f",
            edgecolors="#ffecb3",
            linewidths=1,
            zorder=3,
        )

        planet_colors = {
            "Mercury": "#b0bec5",
            "Venus": "#ffb74d",
            "Earth": "#64b5f6",
            "Mars": "#ef5350",
            "Jupiter": "#a1887f",
            "Saturn": "#ffeb3b",
            "Uranus": "#81d4fa",
            "Neptune": "#5c6bc0",
        }

        for name, (x, y, z) in positions.items():
            color = planet_colors.get(name, "#ba68c8")
            self.ax.scatter(
                x,
                y,
                s=60,
                color=color,
                alpha=0.9,
                edgecolors="#111111",
                linewidths=0.6,
                zorder=4,
            )
            self.ax.text(
                x,
                y,
                name,
                fontsize=9,
                ha="left",
                va="center",
                color=self.fg_color,
                transform=planet_label_transform,
                bbox=dict(
                    boxstyle="round,pad=0.2",
                    facecolor="#000000",
                    alpha=0.6,
                    edgecolor="none",
                ),
                zorder=5,
            )
            xs.append(x)
            ys.append(y)

        if asteroid_label and asteroid_pos:
            ax_, ay_, az_ = asteroid_pos
            self.ax.scatter(ax_, ay_, s=50, marker="x", color="#ffeb3b", zorder=5)
            self.ax.text(
                ax_,
                ay_,
                asteroid_label,
                fontsize=9,
                fontweight="bold",
                ha="left",
                va="center",
                color="#ffeb3b",
                transform=asteroid_label_transform,
                bbox=dict(
                    boxstyle="round,pad=0.2",
                    facecolor="#000000",
                    alpha=0.7,
                    edgecolor="none",
                ),
                zorder=6,
            )
            xs.append(ax_)
            ys.append(ay_)

        from matplotlib.patches import Circle

        displayed_planets = set(positions.keys())
        if xs and ys:
            max_coord = max(max(abs(x) for x in xs), max(abs(y) for y in ys))
        else:
            max_coord = 0

        for name, r in orbit_radii.items():
            if name in displayed_planets or r <= max_coord * 1.5:
                c = Circle(
                    (0, 0),
                    r,
                    fill=False,
                    linestyle="--",
                    linewidth=0.7,
                    alpha=0.35,
                    edgecolor="#616161",
                    zorder=1,
                )
                self.ax.add_patch(c)

        if xs and ys:
            base_radius = max(
                max(abs(x) for x in xs),
                max(abs(y) for y in ys),
            )
        else:
            base_radius = 5.0

        base_radius *= 1.2

        if self.zoom_factor <= 0:
            self.zoom_factor = 1.0

        view_radius = base_radius / self.zoom_factor
        margin = 0.1 * view_radius

        self.ax.set_xlim(-view_radius - margin, view_radius + margin)
        self.ax.set_ylim(-view_radius - margin, view_radius + margin)

        self.ax.set_aspect("equal", "box")
        self.ax.set_xlabel("X (AU)", color=self.fg_color)
        self.ax.set_ylabel("Y (AU)", color=self.fg_color)
        self.ax.tick_params(colors=self.muted_fg)
        for spine in self.ax.spines.values():
            spine.set_color("#444444")

        self.ax.grid(True, linestyle=":", linewidth=0.4, color="#424242", alpha=0.6)
        self.ax.set_title(
            f"Heliocentric XY Plane — {when.strftime('%Y-%m-%d %H:%M UTC')}",
            color=self.fg_color,
        )

        self.fig.tight_layout()
        self.canvas.draw()


def main():
    app = OrbitDashboard()
    app.mainloop()


if __name__ == "__main__":
    main()

