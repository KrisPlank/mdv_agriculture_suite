/** @odoo-module **/

/** Field and farm map on OpenStreetMap tiles (Leaflet, no API key). */
import { _t } from "@web/core/l10n/translation";
import { loadCSS, loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onMounted, onPatched, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";

const LIB = "/mdv_agriculture_suite/static/lib/leaflet/";
const STATE_COLORS = { growing: "#2e7d32", planned: "#f9a825", harvested: "#8d6e63", fallow: "#9e9e9e" };

export function ringAreaHa(ring) {
    // Same geodesic formula as the Python side (models/farm.py ring_area_ha).
    if (ring.length < 3) {
        return 0;
    }
    const R = 6378137;
    const rad = (d) => (d * Math.PI) / 180;
    let total = 0;
    for (let i = 0; i < ring.length; i++) {
        const [lng1, lat1] = ring[i];
        const [lng2, lat2] = ring[(i + 1) % ring.length];
        total += rad(lng2 - lng1) * (2 + Math.sin(rad(lat1)) + Math.sin(rad(lat2)));
    }
    return Math.abs((total * R * R) / 2) / 10000;
}

export class AgriMapField extends Component {
    static template = "mdv_agriculture_suite.AgriMapField";
    static props = {
        ...standardFieldProps,
        latField: { type: String, optional: true },
        lngField: { type: String, optional: true },
        collection: { type: Boolean, optional: true },
        height: { type: Number, optional: true },
    };
    static defaultProps = { height: 380, collection: false };

    setup() {
        this.mapRef = useRef("map");
        this.state = useState({ points: 0, areaHa: 0 });
        onWillStart(async () => {
            await loadCSS(LIB + "leaflet.css");
            await loadJS(LIB + "leaflet.js");
        });
        onMounted(() => this.renderMap());
        onPatched(() => this.refreshLayers());
        onWillUnmount(() => this.map && this.map.remove());
    }

    get editable() {
        return !this.props.readonly && !this.props.collection;
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    parseRing() {
        try {
            const data = JSON.parse(this.value || "null");
            const geom = data && data.type === "Feature" ? data.geometry : data;
            if (geom && geom.type === "Polygon" && geom.coordinates && geom.coordinates[0]) {
                const ring = geom.coordinates[0].map((p) => [p[0], p[1]]);
                if (ring.length > 1 && ring[0][0] === ring.at(-1)[0] && ring[0][1] === ring.at(-1)[1]) {
                    ring.pop();
                }
                return ring;
            }
        } catch {
            // invalid json: start from an empty polygon
        }
        return [];
    }

    center() {
        const data = this.props.record.data;
        const lat = this.props.latField ? data[this.props.latField] : 0;
        const lng = this.props.lngField ? data[this.props.lngField] : 0;
        return lat || lng ? [lat, lng] : null;
    }

    renderMap() {
        const L = window.L;
        L.Icon.Default.imagePath = LIB + "images/";
        this.map = L.map(this.mapRef.el, { scrollWheelZoom: false });
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors",
        }).addTo(this.map);
        this.layer = L.layerGroup().addTo(this.map);
        if (this.editable) {
            this.map.on("click", (ev) => this.addPoint(ev.latlng));
        }
        this.refreshLayers(true);
    }

    refreshLayers(fit = false) {
        if (!this.map) {
            return;
        }
        const L = window.L;
        this.layer.clearLayers();
        let bounds = null;
        if (this.props.collection) {
            let data = {};
            try {
                data = JSON.parse(this.value || "{}");
            } catch {
                data = {};
            }
            for (const feature of data.features || []) {
                const color = STATE_COLORS[feature.properties.state] || "#1565c0";
                const poly = L.polygon(
                    feature.geometry.coordinates[0].map((p) => [p[1], p[0]]),
                    { color, weight: 2, fillOpacity: 0.35 }
                ).addTo(this.layer);
                const p = feature.properties;
                poly.bindTooltip(`${p.name} - ${p.area ?? p.area_ha} ${p.area_unit || "ha"}${p.crop ? " - " + p.crop : ""}`, {
                    permanent: true,
                    direction: "center",
                    className: "o_agri_map_label",
                });
                bounds = bounds ? bounds.extend(poly.getBounds()) : poly.getBounds();
            }
            if (!bounds && data.center) {
                this.map.setView(data.center, 14);
            }
        } else {
            const ring = this.parseRing();
            this.state.points = ring.length;
            this.state.areaHa = ringAreaHa(ring);
            if (ring.length) {
                const latlngs = ring.map((p) => [p[1], p[0]]);
                const shape = ring.length >= 3 ? L.polygon(latlngs, { color: "#2e7d32", weight: 2, fillOpacity: 0.3 })
                    : L.polyline(latlngs, { color: "#2e7d32" });
                shape.addTo(this.layer);
                if (this.editable) {
                    for (const ll of latlngs) {
                        L.circleMarker(ll, { radius: 5, color: "#1b5e20", fillOpacity: 1 }).addTo(this.layer);
                    }
                }
                bounds = shape.getBounds();
            }
        }
        if (fit || !this._fitted) {
            if (bounds && bounds.isValid()) {
                this.map.fitBounds(bounds, { padding: [20, 20], maxZoom: 17 });
                this._fitted = true;
            } else if (!this.props.collection) {
                const c = this.center();
                this.map.setView(c || [20, 0], c ? 15 : 2);
            }
        }
        setTimeout(() => this.map && this.map.invalidateSize(), 50);
    }

    writeRing(ring) {
        const value = ring.length
            ? JSON.stringify({ type: "Polygon", coordinates: [[...ring, ring[0]].map((p) => [+p[0].toFixed(7), +p[1].toFixed(7)])] })
            : false;
        this.props.record.update({ [this.props.name]: value });
    }

    addPoint(latlng) {
        const ring = this.parseRing();
        ring.push([latlng.lng, latlng.lat]);
        this.writeRing(ring);
    }

    onUndo() {
        const ring = this.parseRing();
        ring.pop();
        this.writeRing(ring);
    }

    onClear() {
        this.writeRing([]);
    }

    get areaLabel() {
        const imperial = this.props.record.data.mdv_agri_imperial_units;
        return _t("%(points)s points - %(area)s %(unit)s", {
            points: this.state.points,
            area: (this.state.areaHa * (imperial ? 2.4710538 : 1)).toFixed(2),
            unit: imperial ? "acres" : "ha",
        });
    }
}

export const agriMapField = {
    component: AgriMapField,
    displayName: _t("Farm Map"),
    supportedTypes: ["text"],
    extractProps: ({ options }) => ({
        latField: options.lat_field,
        lngField: options.lng_field,
        collection: Boolean(options.collection),
        height: options.height || 380,
    }),
};

registry.category("fields").add("mdv_agri_map", agriMapField);
