import { useEffect, useState } from 'react';
import { AlertCircle, LoaderCircle, Map as MapIcon, RefreshCw } from 'lucide-react';
import L from 'leaflet';
import { Link } from 'react-router-dom';
import { MapContainer, Marker, TileLayer, useMap } from 'react-leaflet';
import { listIncidents } from '../../api/reports.js';
import { getMappableIncidents, getMarkerPresentation } from './incidentMap.js';

const DEFAULT_CENTER = [10.027, 76.308];
const REFRESH_INTERVAL_MS = 30000;

function MapViewport({ incident }) {
  const map = useMap();
  const latitude = incident ? Number(incident.report.latitude) : null;
  const longitude = incident ? Number(incident.report.longitude) : null;

  useEffect(() => {
    if (latitude !== null && longitude !== null) {
      map.flyTo([latitude, longitude], Math.max(map.getZoom(), 12), { duration: 0.35 });
    }
  }, [map, incident?.id, latitude, longitude]);

  return null;
}

function markerIcon(incident, selected) {
  const { statusClass, priorityClass, radius } = getMarkerPresentation(incident);
  const size = radius * 2;
  return L.divIcon({
    className: 'incident-map-marker-shell',
    html: `<span class="incident-map-marker incident-map-marker--${statusClass} incident-map-marker--${priorityClass}${selected ? ' incident-map-marker--selected' : ''}"></span>`,
    iconSize: [size, size],
    iconAnchor: [radius, radius],
  });
}

function displayValue(value) {
  return String(value || 'UNKNOWN').replaceAll('_', ' ');
}

export default function IncidentMapPage() {
  const [incidents, setIncidents] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState(null);
  const locatedIncidents = getMappableIncidents(incidents);
  const selectedIncident = locatedIncidents.find((incident) => incident.id === selectedId) || null;

  useEffect(() => {
    let active = true;

    async function refreshIncidents() {
      setRefreshing(true);
      try {
        const latest = await listIncidents();
        if (!active) return;
        const located = getMappableIncidents(latest);
        setIncidents(latest);
        setSelectedId((current) => located.some((incident) => incident.id === current)
          ? current : located[0]?.id ?? null);
        setUpdatedAt(new Date());
        setError('');
      } catch (requestError) {
        if (active) setError(requestError.message || 'Incident data could not be loaded.');
      } finally {
        if (active) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    }

    refreshIncidents();
    const interval = window.setInterval(refreshIncidents, REFRESH_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [refreshToken]);

  return (
    <>
      <section className="page-heading incident-map-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow__line" />COORDINATOR OPERATIONS</div>
          <h1>Incident map<span className="heading-period">.</span></h1>
          <p>Confirmed incidents at their saved locations.</p>
        </div>
        <button className="button button--quiet incident-map-refresh" type="button"
          onClick={() => setRefreshToken((current) => current + 1)} disabled={refreshing}
          aria-label="Refresh incidents" title="Refresh incidents">
          {refreshing ? <LoaderCircle className="location-spinner" size={16} /> : <RefreshCw size={16} />}
          Refresh
        </button>
      </section>

      {error && <div className="notice notice--error incident-map-error" role="alert">
        <AlertCircle size={17} />{error}
      </div>}

      {loading ? (
        <div className="panel incident-map-state" role="status">
          <LoaderCircle className="location-spinner" size={20} />Loading confirmed incidents…
        </div>
      ) : locatedIncidents.length === 0 ? (
        <div className="panel incident-map-state incident-map-state--empty">
          <MapIcon size={22} />
          <strong>{incidents.length ? 'No incidents have valid saved coordinates.' : 'No confirmed incidents yet.'}</strong>
          <span>{incidents.length ? `${incidents.length} incident${incidents.length === 1 ? '' : 's'} cannot be placed on the map.` : 'Newly confirmed incidents will appear here.'}</span>
          <Link className="button button--quiet" to="/review">Open report review</Link>
        </div>
      ) : (
        <>
          {incidents.length > locatedIncidents.length && (
            <div className="notice notice--warning incident-map-error" role="status">
              {incidents.length - locatedIncidents.length} incident{incidents.length - locatedIncidents.length === 1 ? '' : 's'} with invalid coordinates omitted. Review the source report to correct its location.
              <Link to="/review">Open review</Link>
            </div>
          )}
          <div className="incident-map-toolbar">
            <span>{locatedIncidents.length} LOCATED INCIDENT{locatedIncidents.length === 1 ? '' : 'S'}</span>
            <span role="status">{updatedAt ? `Updated ${updatedAt.toLocaleTimeString()}` : 'Waiting for saved data'}</span>
          </div>
          <div className="incident-map-layout">
            <div className="incident-map-frame" aria-label="Map of confirmed incidents">
              <MapContainer center={DEFAULT_CENTER} zoom={6} scrollWheelZoom className="incident-map-canvas">
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <MapViewport incident={selectedIncident} />
                {locatedIncidents.map((incident) => {
                  const latitude = Number(incident.report.latitude);
                  const longitude = Number(incident.report.longitude);
                  const selected = incident.id === selectedId;
                  return (
                    <Marker key={incident.id} position={[latitude, longitude]}
                      icon={markerIcon(incident, selected)} keyboard
                      title={`${displayValue(incident.status)} incident, ${displayValue(incident.priority_band || 'unrated')} priority`}
                      alt={`${displayValue(incident.status)}; ${displayValue(incident.priority_band || 'unrated')} priority`}
                      eventHandlers={{ click: () => setSelectedId(incident.id) }} />
                  );
                })}
              </MapContainer>
              <span className="incident-map-attribution">Map data © OpenStreetMap contributors</span>
            </div>

            <aside className="incident-map-sidebar" aria-label="Incident map details">
              <section className="incident-map-legend" aria-labelledby="incident-map-legend-title">
                <h2 id="incident-map-legend-title">Map key</h2>
                <div className="incident-map-legend__row">
                  <span className="incident-map-legend__status incident-map-legend__status--confirmed" />
                  <span>Status: Confirmed</span>
                </div>
                <div className="incident-map-legend__row incident-map-legend__row--priority">
                  <span className="incident-map-legend__sizes"><i /><i /><i /><i /></span>
                  <span>Priority: LOW to CRITICAL, larger markers</span>
                </div>
              </section>

              <section className="incident-map-list" aria-label="Located incidents">
                <h2>Located incidents <span>{locatedIncidents.length}</span></h2>
                <ul>
                  {locatedIncidents.map((incident) => (
                    <li key={incident.id}>
                      <button type="button" className={`incident-map-item${incident.id === selectedId ? ' incident-map-item--active' : ''}`}
                        onClick={() => setSelectedId(incident.id)} aria-current={incident.id === selectedId ? 'true' : undefined}>
                        <span className={`incident-map-item__status incident-map-item__status--${getMarkerPresentation(incident).statusClass}`} />
                        <span className="incident-map-item__text">
                          <strong>{displayValue(incident.report.disaster_type)}</strong>
                          <small>{incident.report.location_name || `${incident.report.latitude}, ${incident.report.longitude}`}</small>
                        </span>
                        <span className="incident-map-item__priority">{displayValue(incident.priority_band || 'UNRATED')}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>

              {selectedIncident && (
                <section className="incident-map-detail" aria-live="polite" aria-labelledby="incident-map-detail-title">
                  <span className="section-kicker">SELECTED INCIDENT</span>
                  <h2 id="incident-map-detail-title">{displayValue(selectedIncident.report.disaster_type)}</h2>
                  <dl>
                    <div><dt>Status</dt><dd>{displayValue(selectedIncident.status)}</dd></div>
                    <div><dt>Priority</dt><dd>{displayValue(selectedIncident.priority_band || 'UNRATED')}{selectedIncident.priority_score != null ? ` · ${Math.round(selectedIncident.priority_score)}/100` : ''}</dd></div>
                    <div><dt>Location</dt><dd>{selectedIncident.report.location_name || 'Unnamed location'}</dd></div>
                    <div><dt>Coordinates</dt><dd>{selectedIncident.report.latitude}, {selectedIncident.report.longitude}</dd></div>
                  </dl>
                  <p>{selectedIncident.report.description}</p>
                  {selectedIncident.priority_is_overridden && <small>Priority adjusted by a coordinator.</small>}
                </section>
              )}
            </aside>
          </div>
        </>
      )}
    </>
  );
}