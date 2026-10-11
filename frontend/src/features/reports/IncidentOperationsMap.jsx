import { useEffect, useState } from 'react';
import { AlertCircle, Check, LoaderCircle, MapPin, Save } from 'lucide-react';
import L from 'leaflet';
import markerIconUrl from 'leaflet/dist/images/marker-icon.png';
import markerRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png';
import markerShadowUrl from 'leaflet/dist/images/marker-shadow.png';
import { Circle, GeoJSON, MapContainer, Marker, Popup, TileLayer } from 'react-leaflet';
import { useAuth } from '../auth/AuthProvider.jsx';
import {
  findNearbyResources,
  getImpactArea,
  registerResource,
  saveImpactArea,
} from '../../api/reports.js';
import '../../styles/operations.css';

const incidentIcon = L.icon({
  iconUrl: markerIconUrl,
  iconRetinaUrl: markerRetinaUrl,
  shadowUrl: markerShadowUrl,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});
const resourceIcon = L.divIcon({
  className: 'operations-resource-icon',
  html: '<span></span>',
  iconSize: [19, 19],
  iconAnchor: [9, 9],
});

export default function IncidentOperationsMap({ incidentId, report }) {
  const { user } = useAuth();
  const [impactArea, setImpactArea] = useState(null);
  const [geometryType, setGeometryType] = useState('RADIUS');
  const [radius, setRadius] = useState('5000');
  const [polygonText, setPolygonText] = useState('');
  const [resources, setResources] = useState([]);
  const [radiusLimit, setRadiusLimit] = useState(null);
  const [impactError, setImpactError] = useState('');
  const [resourceError, setResourceError] = useState('');
  const [resourceMessage, setResourceMessage] = useState('');
  const [loadingArea, setLoadingArea] = useState(true);
  const [loadingResources, setLoadingResources] = useState(true);
  const [savingArea, setSavingArea] = useState(false);
  const [registering, setRegistering] = useState(false);

  async function refreshResources() {
    setLoadingResources(true);
    setResourceError('');
    try {
      const result = await findNearbyResources(incidentId);
      setResources(result.resources);
      setRadiusLimit(result.radius_m);
    } catch (error) {
      setResourceError(error.message);
    } finally {
      setLoadingResources(false);
    }
  }

  useEffect(() => {
    let active = true;
    setLoadingArea(true);
    setImpactError('');
    getImpactArea(incidentId).then((area) => {
      if (!active) return;
      setImpactArea(area);
      if (area) {
        setGeometryType(area.geometry_type);
        setRadius(String(area.radius_m ?? 5000));
        setPolygonText(area.polygon ? JSON.stringify(area.polygon, null, 2) : '');
      } else {
        setGeometryType('RADIUS');
        setRadius('5000');
        setPolygonText('');
      }
    }).catch((error) => {
      if (active) setImpactError(error.message);
    }).finally(() => {
      if (active) setLoadingArea(false);
    });
    return () => { active = false; };
  }, [incidentId]);

  useEffect(() => {
    refreshResources();
  }, [incidentId]);

  async function submitImpactArea(event) {
    event.preventDefault();
    setImpactError('');
    setSavingArea(true);
    try {
      let body;
      if (geometryType === 'RADIUS') {
        body = { geometry_type: 'RADIUS', radius_m: Number(radius), polygon: null };
      } else {
        body = {
          geometry_type: 'POLYGON',
          radius_m: null,
          polygon: JSON.parse(polygonText),
        };
      }
      const saved = await saveImpactArea(incidentId, body);
      setImpactArea(saved);
      setImpactError('');
    } catch (error) {
      setImpactError(error instanceof SyntaxError
        ? 'Polygon must be valid GeoJSON. Check the JSON syntax and try again.'
        : error.message);
    } finally {
      setSavingArea(false);
    }
  }

  async function submitResource(event) {
    event.preventDefault();
    setResourceError('');
    setResourceMessage('');
    setRegistering(true);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const latitudeText = String(form.get('latitude') || '').trim();
    const longitudeText = String(form.get('longitude') || '').trim();
    try {
      await registerResource({
        name: String(form.get('name') || ''),
        latitude: latitudeText ? Number(latitudeText) : null,
        longitude: longitudeText ? Number(longitudeText) : null,
        capabilities: String(form.get('capabilities') || '')
          .split(',').map((value) => value.trim()).filter(Boolean),
        status: String(form.get('status') || 'AVAILABLE'),
      });
      formElement.reset();
      setResourceMessage('Resource registered.');
      await refreshResources();
    } catch (error) {
      setResourceError(error.message);
    } finally {
      setRegistering(false);
    }
  }

  const center = [Number(report.latitude), Number(report.longitude)];
  const areaStyle = {
    color: '#df7b41',
    fillColor: '#efaa63',
    fillOpacity: 0.24,
    weight: 3,
  };

  return (
    <section className="panel operations-panel" aria-labelledby="operations-map-title">
      <div className="panel-heading">
        <div><span className="section-kicker">COORDINATION MAP</span><h2 id="operations-map-title">Impact area and nearby resources</h2></div>
      </div>
      <div className="operations-map" aria-label="Incident impact and support resource map">
        <MapContainer center={center} zoom={12} scrollWheelZoom className="operations-map__canvas">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <Marker position={center} icon={incidentIcon}>
            <Popup><strong>Incident</strong><br />{report.location_name || report.disaster_type.replaceAll('_', ' ')}</Popup>
          </Marker>
          {impactArea?.geometry_type === 'RADIUS' && (
            <Circle center={center} radius={impactArea.radius_m} pathOptions={areaStyle} />
          )}
          {impactArea?.geometry_type === 'POLYGON' && (
            <GeoJSON data={impactArea.polygon} style={areaStyle} />
          )}
          {resources.map((resource) => (
            <Marker key={resource.id} position={[resource.latitude, resource.longitude]} icon={resourceIcon}>
              <Popup>
                <strong>{resource.name}</strong><br />
                Status: {resource.status}<br />
                Capabilities: {resource.capabilities.join(', ') || 'Not specified'}<br />
                Distance: {resource.distance_m.toLocaleString()} m
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>
      <div className="operations-legend" aria-label="Map legend">
        <span><i className="operations-legend__incident" />Incident location</span>
        <span><i className="operations-legend__area" />Impact area</span>
        <span><i className="operations-legend__resource" />Registered resource</span>
      </div>

      <div className="operations-columns">
        <form className="operations-form" onSubmit={submitImpactArea}>
          <h3>Incident impact area</h3>
          {impactError && <div className="notice notice--error" role="alert"><AlertCircle size={16} />{impactError}</div>}
          {impactArea && <p className="operations-saved" role="status">Saved {impactArea.geometry_type.toLowerCase()} area, updated {new Date(impactArea.updated_at).toLocaleString()}.</p>}
          {!impactArea && !loadingArea && !impactError && <p className="operations-help">No impact area has been saved for this incident yet.</p>}
          <label className="field"><span>Area type</span>
            <select value={geometryType} onChange={(event) => setGeometryType(event.target.value)}>
              <option value="RADIUS">Radius in metres</option>
              <option value="POLYGON">GeoJSON polygon</option>
            </select>
          </label>
          {geometryType === 'RADIUS' ? (
            <label className="field"><span>Radius (metres)</span>
              <input type="number" min="1" step="1" value={radius}
                onChange={(event) => setRadius(event.target.value)} required />
            </label>
          ) : (
            <label className="field"><span>Polygon (GeoJSON)</span>
              <textarea className="operations-polygon-input" value={polygonText}
                onChange={(event) => setPolygonText(event.target.value)}
                placeholder={'{"type":"Polygon","coordinates":[[[76.29,10.02],[76.31,10.02],[76.31,10.04],[76.29,10.02]]]}'} required />
            </label>
          )}
          <button className="button button--primary" type="submit" disabled={savingArea || loadingArea}>
            {savingArea ? <LoaderCircle className="location-spinner" size={16} /> : <Save size={16} />}
            {savingArea ? 'Saving…' : impactArea ? 'Update impact area' : 'Save impact area'}
          </button>
        </form>

        <div className="operations-resources">
          <h3>Nearby relevant resources</h3>
          {loadingResources ? <p className="operations-help" role="status"><LoaderCircle className="location-spinner" size={15} /> Loading nearby resources…</p> : (
            <>
              <p className="operations-help">Showing AVAILABLE resources within {radiusLimit?.toLocaleString()} m, ranked by capability match and distance.</p>
              {!resources.length && <p className="operations-help">No matching, located resources are currently available nearby.</p>}
              <ul className="resource-results">
                {resources.map((resource) => (
                  <li key={resource.id}>
                    <MapPin size={16} />
                    <span><strong>{resource.name}</strong><small>{resource.capabilities.join(', ') || 'No capabilities listed'} · {resource.distance_m.toLocaleString()} m away</small></span>
                    <b className={`resource-status resource-status--${resource.status.toLowerCase()}`}>{resource.status}</b>
                  </li>
                ))}
              </ul>
            </>
          )}
          {resourceError && <div className="notice notice--error" role="alert"><AlertCircle size={16} />{resourceError}</div>}
          {resourceMessage && <div className="notice notice--success" role="status"><Check size={16} />{resourceMessage}</div>}
          {user?.role === 'ADMIN' && (
            <form className="resource-registration" onSubmit={submitResource}>
              <h4>Register a support resource</h4>
              <label className="field"><span>Name</span><input name="name" maxLength="160" required /></label>
              <div className="field-grid">
                <label className="field"><span>Latitude (optional)</span><input name="latitude" type="number" min="-90" max="90" step="any" /></label>
                <label className="field"><span>Longitude (optional)</span><input name="longitude" type="number" min="-180" max="180" step="any" /></label>
              </div>
              <label className="field"><span>Capabilities (comma-separated)</span><input name="capabilities" placeholder="RESCUE, MEDICAL_AID" /></label>
              <label className="field"><span>Operational status</span><select name="status" defaultValue="AVAILABLE">
                <option value="AVAILABLE">Available</option><option value="BUSY">Busy</option>
                <option value="DEPLOYED">Deployed</option><option value="UNAVAILABLE">Unavailable</option>
              </select></label>
              <button className="button button--quiet" type="submit" disabled={registering}>
                {registering ? 'Registering…' : 'Register resource'}
              </button>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
