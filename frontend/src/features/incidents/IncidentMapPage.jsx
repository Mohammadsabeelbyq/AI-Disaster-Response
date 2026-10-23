import { useEffect, useRef, useState } from 'react';
import { AlertCircle, LoaderCircle, Map as MapIcon, MapPin, RefreshCw, Search } from 'lucide-react';
import L from 'leaflet';
import { Link } from 'react-router-dom';
import { CircleMarker, MapContainer, Marker, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet';
import { listIncidents, listReports } from '../../api/reports.js';
import { parseLocationInput } from '../reports/mapLocation.js';
import { getIncidentCoordinates, getMappableIncidents, getMarkerPresentation, mergeReportsWithIncidents, PRIORITY_LEVELS } from './incidentMap.js';

const DEFAULT_CENTER = [10.027, 76.308];
const REFRESH_INTERVAL_MS = 30000;

function MapViewport({ incident, searchPosition }) {
  const map = useMap();
  const position = searchPosition || getIncidentCoordinates(incident);

  useEffect(() => {
    if (position) {
      map.flyTo(position, Math.max(map.getZoom(), 13), { duration: 0.35 });
    }
  }, [map, incident?.id, position?.[0], position?.[1]]);

  return null;
}

function markerIcon(incident, selected) {
  const { statusClass, priorityClass, priorityColor, radius } = getMarkerPresentation(incident);
  const size = radius * 2;
  return L.divIcon({
    className: 'incident-map-marker-shell',
    html: `<span class="incident-map-marker incident-map-marker--${statusClass} incident-map-marker--${priorityClass}${selected ? ' incident-map-marker--selected' : ''}" style="--incident-priority-color:${priorityColor}"></span>`,
    iconSize: [size, size],
    iconAnchor: [radius, radius],
  });
}

function displayValue(value) {
  return String(value || 'UNKNOWN').replaceAll('_', ' ');
}

function priorityStyle(priority) {
  return {
    '--incident-priority-color': priority.priorityColor ?? priority.color,
    '--incident-priority-text-color': priority.priorityTextColor ?? priority.textColor,
  };
}

export default function IncidentMapPage() {
  const [mapRecords, setMapRecords] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [error, setError] = useState('');
  const [coordinateQuery, setCoordinateQuery] = useState('');
  const [coordinateError, setCoordinateError] = useState('');
  const [searchPosition, setSearchPosition] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const latestRequestId = useRef(0);
  const locatedIncidents = getMappableIncidents(mapRecords);
  const selectedIncident = locatedIncidents.find((incident) => incident.id === selectedId) || null;
  const selectedPresentation = selectedIncident ? getMarkerPresentation(selectedIncident) : null;
  const visibleStatuses = [...new Set(locatedIncidents.map((incident) => getMarkerPresentation(incident).statusClass))];

  function locateCoordinates(event) {
    event.preventDefault();
    const parsed = parseLocationInput(coordinateQuery);
    if (parsed.kind !== 'coordinates') {
      setCoordinateError(parsed.kind === 'error'
        ? parsed.message
        : 'Enter coordinates as latitude, longitude (for example, 10.027, 76.308).');
      return;
    }

    setCoordinateError('');
    setSelectedId(null);
    setSearchPosition([parsed.latitude, parsed.longitude]);
  }

  function selectIncident(incidentId) {
    setSearchPosition(null);
    setSelectedId(incidentId);
  }

  useEffect(() => {
    let active = true;

    async function refreshIncidents() {
      const requestId = ++latestRequestId.current;
      setRefreshing(true);
      try {
        const [reports, incidents] = await Promise.all([listReports(), listIncidents()]);
        if (!active || requestId !== latestRequestId.current) return;
        const latest = mergeReportsWithIncidents(reports, incidents);
        const located = getMappableIncidents(latest);
        setMapRecords(latest);
        setSelectedId((current) => located.some((incident) => incident.id === current)
          ? current : located[0]?.id ?? null);
        setUpdatedAt(new Date());
        setError('');
      } catch (requestError) {
        if (active && requestId === latestRequestId.current) {
          setError(requestError.message || 'Incident data could not be loaded.');
        }
      } finally {
        if (active && requestId === latestRequestId.current) {
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
          <p>Saved reports and confirmed incidents at their recorded locations.</p>
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

      <form className="incident-map-coordinate-form" onSubmit={locateCoordinates}>
        <label htmlFor="incident-map-coordinate-query">Find a point by coordinates</label>
        <div className="incident-map-coordinate-form__controls">
          <div className="location-search__input">
            <Search size={16} />
            <input id="incident-map-coordinate-query" aria-label="Latitude and longitude"
              value={coordinateQuery} onChange={(event) => {
                setCoordinateQuery(event.target.value);
                setCoordinateError('');
              }}
              placeholder="Latitude, longitude (e.g. 10.027, 76.308)" />
          </div>
          <button className="button button--quiet" type="submit"><MapPin size={16} />Locate</button>
        </div>
        {coordinateError && <p className="location-error" role="alert">{coordinateError}</p>}
      </form>

      {loading ? (
        <div className="panel incident-map-state" role="status">
          <LoaderCircle className="location-spinner" size={20} />Loading confirmed incidents…
        </div>
      ) : locatedIncidents.length === 0 && !searchPosition ? (
        <div className="panel incident-map-state incident-map-state--empty">
          <MapIcon size={22} />
          <strong>{mapRecords.length ? 'No saved locations are valid for the map.' : 'No saved reports or confirmed incidents yet.'}</strong>
          <span>{mapRecords.length ? `${mapRecords.length} record${mapRecords.length === 1 ? '' : 's'} cannot be placed on the map.` : 'New reports and confirmed incidents will appear here.'}</span>
          <Link className="button button--quiet" to="/review">Open report review</Link>
        </div>
      ) : (
        <>
          {locatedIncidents.length === 0 && searchPosition && (
            <p className="incident-map-coordinate-note" role="status">
              No located incidents to display. Showing the requested coordinates only.
            </p>
          )}
          {mapRecords.length > locatedIncidents.length && (
            <div className="notice notice--warning incident-map-error" role="status">
              {mapRecords.length - locatedIncidents.length} record{mapRecords.length - locatedIncidents.length === 1 ? '' : 's'} with invalid coordinates omitted. Review the source report to correct its location.
              <Link to="/review">Open review</Link>
            </div>
          )}
          <div className="incident-map-toolbar">
            <span>{locatedIncidents.length} LOCATED RECORD{locatedIncidents.length === 1 ? '' : 'S'}</span>
            <span role="status">{updatedAt ? `Updated ${updatedAt.toLocaleTimeString()}` : 'Waiting for saved data'}</span>
          </div>
          <div className="incident-map-layout">
            <div className="incident-map-frame" aria-label="Map of confirmed incidents">
              <MapContainer center={DEFAULT_CENTER} zoom={6} scrollWheelZoom className="incident-map-canvas">
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <MapViewport incident={selectedIncident} searchPosition={searchPosition} />
                {searchPosition && (
                  <CircleMarker center={searchPosition} radius={9}
                    pathOptions={{ color: '#174c42', weight: 3, fillColor: '#e9ad43', fillOpacity: 1 }}>
                    <Popup>
                      Coordinate location<br />
                      {searchPosition[0]}, {searchPosition[1]}
                    </Popup>
                  </CircleMarker>
                )}
                {locatedIncidents.map((incident) => {
                  const position = getIncidentCoordinates(incident);
                  const selected = incident.id === selectedId;
                  return (
                    <Marker key={incident.id} position={position}
                      icon={markerIcon(incident, selected)} keyboard
                      title={`${displayValue(incident.status)} incident, ${getMarkerPresentation(incident).priorityLabel} priority`}
                      alt={`${displayValue(incident.status)}; ${getMarkerPresentation(incident).priorityLabel} priority`}
                      eventHandlers={{ click: () => selectIncident(incident.id) }}>
                      <Tooltip>{`${getMarkerPresentation(incident).priorityLabel} priority`}</Tooltip>
                    </Marker>
                  );
                })}
              </MapContainer>
              <span className="incident-map-attribution">Map data © OpenStreetMap contributors</span>
            </div>

            <aside className="incident-map-sidebar" aria-label="Incident map details">
              <section className="incident-map-legend" aria-labelledby="incident-map-legend-title">
                <h2 id="incident-map-legend-title">Map key</h2>
                {visibleStatuses.map((statusClass) => (
                  <div className="incident-map-legend__row" key={statusClass}>
                    <span className={`incident-map-legend__status incident-map-legend__status--${statusClass}`} />
                    <span>Status: {displayValue(statusClass).toUpperCase()}</span>
                  </div>
                ))}
                <div className="incident-map-legend__row"><span>Priority colors:</span></div>
                <div className="incident-map-priority-legend" aria-label="Priority color scale">
                  {PRIORITY_LEVELS.map((priority) => (
                    <span key={priority.band} style={priorityStyle(priority)}>
                      <i aria-hidden="true" />{priority.label}
                    </span>
                  ))}
                </div>
                <div className="incident-map-legend__note">Larger markers indicate higher priority.</div>
              </section>

              <section className="incident-map-list" aria-label="Located incidents">
                <h2>Located incidents <span>{locatedIncidents.length}</span></h2>
                <ul>
                  {locatedIncidents.map((incident) => (
                    <li key={incident.id}>
                      <button type="button" className={`incident-map-item${incident.id === selectedId ? ' incident-map-item--active' : ''}`}
                        onClick={() => selectIncident(incident.id)}
                        aria-label={`${displayValue(incident.report.disaster_type)}, ${displayValue(incident.status)} status, ${getMarkerPresentation(incident).priorityLabel} priority`}
                        aria-current={incident.id === selectedId ? 'true' : undefined}>
                        <span className={`incident-map-item__status incident-map-item__status--${getMarkerPresentation(incident).statusClass}`} />
                        <span className="incident-map-item__text">
                          <strong>{displayValue(incident.report.disaster_type)}</strong>
                          <small>{incident.report.location_name || `${incident.report.latitude}, ${incident.report.longitude}`}</small>
                        </span>
                        <span className="incident-map-item__status-label">{displayValue(incident.status)}</span>
                        <span className="incident-map-item__priority" style={priorityStyle(getMarkerPresentation(incident))}>
                          {getMarkerPresentation(incident).priorityLabel}
                        </span>
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
                    <div><dt>ID</dt><dd>{selectedIncident.id}</dd></div>
                    <div>
                      <dt>Status</dt>
                      <dd className="incident-map-detail__status-value">
                        <span className={`incident-map-item__status incident-map-item__status--${selectedPresentation.statusClass}`} />
                        {displayValue(selectedIncident.status)}
                      </dd>
                    </div>
                    <div>
                      <dt>Priority</dt>
                      <dd>
                        <span className={`incident-map-priority-badge incident-map-priority-badge--${selectedPresentation.priorityClass}`}
                          style={priorityStyle(selectedPresentation)}>
                          {selectedPresentation.priorityLabel}
                        </span>
                        {selectedIncident.priority_score != null ? ` · ${Math.round(selectedIncident.priority_score)}/100` : ''}
                      </dd>
                    </div>
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