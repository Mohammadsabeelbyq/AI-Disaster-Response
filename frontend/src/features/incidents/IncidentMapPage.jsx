import { useEffect, useRef, useState } from 'react';
import { AlertCircle, LoaderCircle, Map as MapIcon, MapPin, RefreshCw, Search } from 'lucide-react';
import L from 'leaflet';
import { Link } from 'react-router-dom';
import { Circle, CircleMarker, GeoJSON, MapContainer, Marker, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet';
import { getIncidentImpactArea, listIncidents, listNearbyResources, listReports } from '../../api/reports.js';
import { parseLocationInput } from '../reports/mapLocation.js';
import { filterAndSortIncidents, getIncidentCoordinates, getMappableIncidents, getMarkerPresentation, mergeReportsWithIncidents, PRIORITY_LEVELS } from './incidentMap.js';

const REFRESH_INTERVAL_MS = 30000;
const RESOURCE_STATES = ['AVAILABLE', 'BUSY', 'DEPLOYED', 'ASSIGNED', 'UNAVAILABLE', 'INACTIVE', 'MAINTENANCE'];
const RESOURCE_STATE_COLORS = {
  AVAILABLE: '#2b7256',
  BUSY: '#bd7b18',
  DEPLOYED: '#3976a8',
  ASSIGNED: '#775b8b',
  UNAVAILABLE: '#a64135',
  INACTIVE: '#78837d',
  MAINTENANCE: '#a64135',
};

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

function incidentTime(incident) {
  return incident.confirmed_at || incident.report?.submitted_at || '';
}

function formatIncidentTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString();
}

function priorityStyle(priority) {
  return {
    '--incident-priority-color': priority.priorityColor ?? priority.color,
    '--incident-priority-text-color': priority.priorityTextColor ?? priority.textColor,
  };
}

export default function IncidentMapPage() {
  const [mapRecords, setMapRecords] = useState([]);
  const [impactArea, setImpactArea] = useState(null);
  const [nearbyResources, setNearbyResources] = useState([]);
  const [resourcesLoading, setResourcesLoading] = useState(false);
  const [resourceError, setResourceError] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [error, setError] = useState('');
  const [coordinateQuery, setCoordinateQuery] = useState('');
  const [coordinateError, setCoordinateError] = useState('');
  const [searchPosition, setSearchPosition] = useState(null);
  const [queueStatus, setQueueStatus] = useState('ALL');
  const [queueType, setQueueType] = useState('ALL');
  const [queueTimeRange, setQueueTimeRange] = useState('ALL');
  const [queueSort, setQueueSort] = useState('NEWEST');
  const [updatedAt, setUpdatedAt] = useState(null);
  const latestRequestId = useRef(0);
  const queueIncidents = filterAndSortIncidents(mapRecords, {
    status: queueStatus,
    type: queueType,
    timeRange: queueTimeRange,
    sortBy: queueSort,
  });
  const locatedIncidents = getMappableIncidents(mapRecords);
  const visibleLocatedIncidents = getMappableIncidents(queueIncidents);
  const initialMapCenter = visibleLocatedIncidents.length
    ? getIncidentCoordinates(visibleLocatedIncidents[0]) : [0, 0];
  const selectedIncident = queueIncidents.find((incident) => incident.id === selectedId)
    || queueIncidents[0] || null;
  const selectedPresentation = selectedIncident ? getMarkerPresentation(selectedIncident) : null;
  const visibleStatuses = [...new Set(visibleLocatedIncidents.map((incident) => getMarkerPresentation(incident).statusClass))];
  const queueStatuses = [...new Set(mapRecords.map((incident) => incident.status).filter(Boolean))].sort();
  const queueTypes = [...new Set(mapRecords.map((incident) => incident.report?.disaster_type).filter(Boolean))].sort();

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
        setSelectedId((current) => latest.some((incident) => incident.id === current)
          ? current : located[0]?.id ?? latest[0]?.id ?? null);
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

  useEffect(() => {
    let active = true;
    if (!selectedIncident || !['CONFIRMED', 'ACTIVE'].includes(selectedIncident.status)) {
      setImpactArea(null);
      setNearbyResources([]);
      setResourcesLoading(false);
      setResourceError('');
      return () => { active = false; };
    }

    setResourcesLoading(true);
    Promise.all([
      getIncidentImpactArea(selectedIncident.id),
      listNearbyResources(selectedIncident.id, RESOURCE_STATES),
    ]).then(([area, resources]) => {
      if (!active) return;
      setImpactArea(area);
      setNearbyResources(resources.resources || []);
      setResourceError('');
    }).catch((requestError) => {
      if (active) setResourceError(requestError.message || 'Nearby resources could not be loaded.');
    }).finally(() => active && setResourcesLoading(false));

    return () => { active = false; };
  }, [selectedIncident?.id, selectedIncident?.status, updatedAt]);

  return (
    <>
      <section className="page-heading incident-map-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow__line" />COORDINATOR OPERATIONS</div>
          <h1>Incident queue<span className="heading-period">.</span></h1>
          <p>Filter and prioritize incoming reports and confirmed incidents, then explore their locations and nearby resources.</p>
        </div>
        <div className="incident-map-heading__actions">
          <Link className="button button--primary" to="/review">Coordinator review & planning</Link>
          <button className="button button--quiet incident-map-refresh" type="button"
            onClick={() => setRefreshToken((current) => current + 1)} disabled={refreshing}
            aria-label="Refresh incidents" title="Refresh incidents">
            {refreshing ? <LoaderCircle className="location-spinner" size={16} /> : <RefreshCw size={16} />}
            Refresh
          </button>
        </div>
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
      ) : mapRecords.length === 0 && !searchPosition ? (
        <div className="panel incident-map-state incident-map-state--empty">
          <MapIcon size={22} />
          <strong>No saved reports or confirmed incidents yet.</strong>
          <span>New reports and confirmed incidents will appear here.</span>
          <Link className="button button--quiet" to="/review">Open report review</Link>
        </div>
      ) : (
        <>
          {locatedIncidents.length === 0 && !searchPosition && (
            <p className="incident-map-coordinate-note" role="status">
              No saved records have valid coordinates. The incident queue is still available below.
            </p>
          )}
          {mapRecords.length > locatedIncidents.length && (
            <div className="notice notice--warning incident-map-error" role="status">
              {mapRecords.length - locatedIncidents.length} record{mapRecords.length - locatedIncidents.length === 1 ? '' : 's'} with invalid coordinates omitted. Review the source report to correct its location.
              <Link to="/review">Open review</Link>
            </div>
          )}
          <div className="incident-map-toolbar">
            <span>{visibleLocatedIncidents.length} LOCATED RECORD{visibleLocatedIncidents.length === 1 ? '' : 'S'} ON MAP</span>
            <span role="status">{updatedAt ? `Updated ${updatedAt.toLocaleTimeString()}` : 'Waiting for saved data'}</span>
          </div>
          <section className="incident-queue" aria-label="Incident queue">
            <div className="incident-queue__heading">
              <div>
                <h2>Incident queue</h2>
                <p>{queueIncidents.length} of {mapRecords.length} records match the selected conditions.</p>
              </div>
              <button className="button button--quiet" type="button"
                onClick={() => {
                  setQueueStatus('ALL');
                  setQueueType('ALL');
                  setQueueTimeRange('ALL');
                  setQueueSort('NEWEST');
                }}>
                Clear filters
              </button>
            </div>
            <div className="incident-queue__filters">
              <label>
                Status
                <select value={queueStatus} onChange={(event) => setQueueStatus(event.target.value)}>
                  <option value="ALL">All statuses</option>
                  {queueStatuses.map((status) => <option key={status} value={status}>{displayValue(status)}</option>)}
                </select>
              </label>
              <label>
                Type
                <select value={queueType} onChange={(event) => setQueueType(event.target.value)}>
                  <option value="ALL">All types</option>
                  {queueTypes.map((type) => <option key={type} value={type}>{displayValue(type)}</option>)}
                </select>
              </label>
              <label>
                Time period
                <select value={queueTimeRange} onChange={(event) => setQueueTimeRange(event.target.value)}>
                  <option value="ALL">All time</option>
                  <option value="24H">Last 24 hours</option>
                  <option value="7D">Last 7 days</option>
                  <option value="30D">Last 30 days</option>
                </select>
              </label>
              <label>
                Sort by
                <select value={queueSort} onChange={(event) => setQueueSort(event.target.value)}>
                  <option value="NEWEST">Newest first</option>
                  <option value="OLDEST">Oldest first</option>
                  <option value="PRIORITY_HIGH">Highest priority</option>
                  <option value="PRIORITY_LOW">Lowest priority</option>
                </select>
              </label>
            </div>
            {queueIncidents.length ? (
              <ul className="incident-queue__items">
                {queueIncidents.map((incident) => {
                  const presentation = getMarkerPresentation(incident);
                  const timestamp = incidentTime(incident);
                  return (
                    <li key={incident.id}>
                      <button type="button" className={`incident-map-item${incident.id === selectedIncident?.id ? ' incident-map-item--active' : ''}`}
                        onClick={() => selectIncident(incident.id)}
                        aria-label={`${displayValue(incident.report?.disaster_type)}, ${displayValue(incident.status)} status, ${presentation.priorityLabel} priority`}
                        aria-current={incident.id === selectedIncident?.id ? 'true' : undefined}>
                        <span className={`incident-map-item__status incident-map-item__status--${presentation.statusClass}`} />
                        <span className="incident-map-item__text">
                          <strong>{displayValue(incident.report?.disaster_type)}</strong>
                          <small>{incident.report?.location_name || 'Location unavailable'}</small>
                        </span>
                        <span className="incident-map-item__status-label">{displayValue(incident.status)}</span>
                        <span className="incident-map-item__priority" style={priorityStyle(presentation)}>
                          {presentation.priorityLabel}
                        </span>
                        <time className="incident-queue__time" dateTime={timestamp || undefined}>
                          {formatIncidentTime(timestamp)}
                        </time>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="incident-queue__empty" role="status">No records match these filters.</p>
            )}
          </section>
          <div className="incident-map-layout">
            <div className="incident-map-frame" aria-label="Map of confirmed incidents">
              <MapContainer center={initialMapCenter} zoom={locatedIncidents.length ? 6 : 2} scrollWheelZoom className="incident-map-canvas">
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
                {selectedIncident && impactArea?.geometry_type === 'RADIUS' && impactArea.radius_m && (
                  <Circle center={getIncidentCoordinates(selectedIncident)} radius={impactArea.radius_m}
                    pathOptions={{ color: '#b87918', weight: 2, fillColor: '#e9ad43', fillOpacity: 0.12 }}>
                    <Tooltip>Configured impact radius: {impactArea.radius_m} m</Tooltip>
                  </Circle>
                )}
                {selectedIncident && impactArea?.geometry_type === 'POLYGON' && impactArea.polygon && (
                  <GeoJSON data={impactArea.polygon}
                    style={{ color: '#b87918', weight: 2, fillColor: '#e9ad43', fillOpacity: 0.12 }} />
                )}
                {nearbyResources.map((resource) => (
                  <CircleMarker key={resource.id} center={[resource.latitude, resource.longitude]}
                    radius={6}
                    pathOptions={{
                      color: '#ffffff',
                      weight: 2,
                      fillColor: RESOURCE_STATE_COLORS[resource.availability] || '#78837d',
                      fillOpacity: 0.95,
                    }}>
                    <Tooltip>{resource.name} · {resource.availability}</Tooltip>
                    <Popup>
                      <strong>{resource.name}</strong><br />
                      {resource.department_name} · {resource.resource_type || 'Unknown'}<br />
                      {resource.availability} · {resource.distance_m} m
                    </Popup>
                  </CircleMarker>
                ))}
                {visibleLocatedIncidents.map((incident) => {
                  const position = getIncidentCoordinates(incident);
                  const selected = incident.id === selectedIncident?.id;
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
              {visibleLocatedIncidents.length === 0 && !searchPosition && (
                <span className="incident-map-no-results" role="status">
                  No matching records with valid map coordinates.
                </span>
              )}
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
                <div className="incident-map-legend__note">Submitted reports are pending review and are not priority-scored yet.</div>
              </section>

              {selectedIncident && (
                <section className="incident-map-detail" aria-live="polite" aria-labelledby="incident-map-detail-title">
                  <span className="section-kicker">SELECTED REPORT / INCIDENT</span>
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
                  <Link className="button button--quiet" to={`/review?reportId=${encodeURIComponent(selectedIncident.report_id || selectedIncident.id)}`}>
                    Review this report
                  </Link>
                </section>
              )}
              {selectedIncident && (
                <section className="incident-map-resources" aria-labelledby="incident-map-resources-title">
                  <div className="incident-map-resources__heading">
                    <h2 id="incident-map-resources-title">Nearby registered resources</h2>
                    <span>{resourcesLoading ? 'Updating…' : nearbyResources.length}</span>
                  </div>
                  {resourceError ? (
                    <p role="alert">{resourceError}</p>
                  ) : nearbyResources.length ? (
                    <ul>
                      {nearbyResources.map((resource) => (
                        <li key={resource.id}>
                          <strong>{resource.name}</strong>
                          <span>{resource.department_name} · {resource.distance_m} m</span>
                          <span>{resource.capabilities.join(', ') || 'No capabilities recorded'}</span>
                          <small style={{ color: RESOURCE_STATE_COLORS[resource.availability] }}>
                            {displayValue(resource.availability)}
                          </small>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>{resourcesLoading
                      ? 'Loading nearby resource state.'
                      : !['CONFIRMED', 'ACTIVE'].includes(selectedIncident.status)
                        ? 'Confirm this report in coordinator review to calculate priority and load matching resources.'
                        : 'No registered resources match the location and capabilities.'}</p>
                  )}
                </section>
              )}
            </aside>
          </div>
        </>
      )}
    </>
  );
}