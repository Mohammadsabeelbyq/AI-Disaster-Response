import { useEffect, useRef, useState } from 'react';
import { Crosshair, LoaderCircle, MapPin, Search } from 'lucide-react';
import L from 'leaflet';
import markerIconUrl from 'leaflet/dist/images/marker-icon.png';
import markerRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png';
import markerShadowUrl from 'leaflet/dist/images/marker-shadow.png';
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import { parseLocationInput } from './mapLocation.js';

const DEFAULT_CENTER = [10.027, 76.308];
const markerIcon = L.icon({
  iconUrl: markerIconUrl,
  iconRetinaUrl: markerRetinaUrl,
  shadowUrl: markerShadowUrl,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

let nominatimQueue = Promise.resolve();
let lastNominatimRequest = 0;

function requestNominatim(path) {
  const nextRequest = nominatimQueue.then(async () => {
    const delay = Math.max(0, 1000 - (Date.now() - lastNominatimRequest));
    if (delay) await new Promise((resolve) => window.setTimeout(resolve, delay));
    lastNominatimRequest = Date.now();
    const response = await fetch(`https://nominatim.openstreetmap.org${path}`, {
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error('The location service is unavailable. Please try again.');
    return response.json();
  });
  nominatimQueue = nextRequest.catch(() => {});
  return nextRequest;
}

function getPlaceName(result) {
  const address = result.address || {};
  const place = result.name || address.neighbourhood || address.suburb
    || address.city_district || address.city || address.town || address.village
    || address.county || result.display_name || '';
  return place.slice(0, 255);
}

function MapViewport({ position }) {
  const map = useMap();
  useEffect(() => {
    if (position) map.flyTo(position, Math.max(map.getZoom(), 13), { duration: 0.45 });
  }, [map, position]);
  return null;
}

function MapClickHandler({ onSelect }) {
  useMapEvents({ click: (event) => onSelect(event.latlng.lat, event.latlng.lng) });
  return null;
}

export default function LocationPicker({ value, onChange }) {
  const [query, setQuery] = useState('');
  const [position, setPosition] = useState(null);
  const [results, setResults] = useState([]);
  const [error, setError] = useState('');
  const [searching, setSearching] = useState(false);
  const [locating, setLocating] = useState(false);
  const [reverseSearching, setReverseSearching] = useState(false);
  const lookupId = useRef(0);

  useEffect(() => {
    if (value.latitude && value.longitude) {
      setPosition([Number(value.latitude), Number(value.longitude)]);
    } else {
      lookupId.current += 1;
      setPosition(null);
      setReverseSearching(false);
    }
  }, [value.latitude, value.longitude]);

  async function selectCoordinates(latitude, longitude, placeName = '') {
    const lat = Number(latitude);
    const lon = Number(longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      setError('Those coordinates are outside the valid latitude/longitude range.');
      return;
    }

    const requestId = ++lookupId.current;
    const nextPosition = [lat, lon];
    setPosition(nextPosition);
    setResults([]);
    setError('');
    onChange({ latitude: lat.toFixed(6), longitude: lon.toFixed(6), location_name: placeName });

    if (placeName) {
      setReverseSearching(false);
      return;
    }

    setReverseSearching(true);
    try {
      const params = new URLSearchParams({ format: 'jsonv2', lat: String(lat), lon: String(lon) });
      const result = await requestNominatim(`/reverse?${params}`);
      if (requestId !== lookupId.current) return;
      const name = getPlaceName(result);
      onChange({ latitude: lat.toFixed(6), longitude: lon.toFixed(6), location_name: name });
      if (!name) setError('Location selected. A place name could not be found, but the coordinates are ready.');
    } catch {
      if (requestId === lookupId.current) {
        setError('Location selected, but its place name could not be looked up. The coordinates are ready.');
      }
    } finally {
      if (requestId === lookupId.current) setReverseSearching(false);
    }
  }

  async function searchLocation() {
    const parsed = parseLocationInput(query);
    if (parsed.kind === 'error') {
      setError(parsed.message);
      setResults([]);
      return;
    }
    if (parsed.kind === 'coordinates') {
      await selectCoordinates(parsed.latitude, parsed.longitude);
      return;
    }
    if (!parsed.query) {
      setError('Enter a place/address, coordinates, or a supported Google Maps link.');
      return;
    }

    setSearching(true);
    setError('');
    setResults([]);
    try {
      const params = new URLSearchParams({ format: 'jsonv2', limit: '5', q: parsed.query });
      const matches = await requestNominatim(`/search?${params}`);
      if (!matches.length) {
        setError('No matching place was found. Try a nearby town, street, or landmark.');
        return;
      }
      setResults(matches.map((place) => ({
        latitude: Number(place.lat),
        longitude: Number(place.lon),
        name: getPlaceName(place),
        displayName: place.display_name,
      })));
    } catch (requestError) {
      setError(requestError.message || 'Could not search that location. Please try again.');
    } finally {
      setSearching(false);
    }
  }

  function handleQueryChange(nextQuery) {
    setQuery(nextQuery);
    setError('');
    setResults([]);
    const parsed = parseLocationInput(nextQuery);
    if (parsed.kind === 'coordinates') selectCoordinates(parsed.latitude, parsed.longitude);
    else if (parsed.kind === 'error' && /^https?:\/\//i.test(nextQuery.trim())) setError(parsed.message);
  }

  function useCurrentLocation() {
    setError('');
    if (!navigator.geolocation) {
      setError('Current location is not available in this browser.');
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setLocating(false);
        selectCoordinates(coords.latitude, coords.longitude);
      },
      (geoError) => {
        setLocating(false);
        const message = geoError.code === 1
          ? 'Location permission was denied. Allow location access or choose a point on the map.'
          : geoError.code === 3
            ? 'Location lookup timed out. Please try again or choose a point on the map.'
            : 'Your current location could not be determined. Choose a point on the map instead.';
        setError(message);
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  }

  const mapCenter = position || DEFAULT_CENTER;

  return (
    <section className="location-picker" aria-labelledby="map-location-title">
      <div className="location-picker__heading">
        <div>
          <h3 id="map-location-title">Map Location <b>*</b></h3>
          <p>Search for a place, paste coordinates, or click and drag the marker.</p>
        </div>
      </div>
      <div className="location-search">
        <div className="location-search__input">
          <Search size={16} />
          <input aria-label="Search location or paste Google Maps link" value={query}
            onChange={(event) => handleQueryChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                searchLocation();
              }
            }}
            placeholder="Search location or paste Google Maps link" />
        </div>
        <button className="button button--quiet location-search__button" type="button" disabled={searching} onClick={searchLocation}>
          {searching ? <LoaderCircle className="location-spinner" size={16} /> : <Search size={16} />}Search
        </button>
      </div>

      {results.length > 0 && (
        <div className="location-results" aria-label="Location search results">
          {results.map((result, index) => (
            <button key={`${result.latitude}-${result.longitude}-${index}`} type="button"
              className="location-result"
              onClick={() => selectCoordinates(result.latitude, result.longitude, result.name)}>
              <MapPin size={15} />
              <span><strong>{result.name || result.displayName}</strong><small>{result.displayName}</small></span>
            </button>
          ))}
        </div>
      )}

      <div className="location-map" aria-label="Interactive map location selector">
        <MapContainer center={mapCenter} zoom={position ? 13 : 8} scrollWheelZoom className="location-map__canvas">
          <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          <MapClickHandler onSelect={selectCoordinates} />
          <MapViewport position={position} />
          {position && <Marker position={position} icon={markerIcon} draggable
            eventHandlers={{ dragend(event) {
              const point = event.target.getLatLng();
              selectCoordinates(point.lat, point.lng);
            } }} />}
        </MapContainer>
        {!position && <div className="location-map__prompt"><MapPin size={15} />Click the map to place a marker</div>}
      </div>

      <div className="location-map__footer">
        <button className="button button--quiet current-location-button" type="button" onClick={useCurrentLocation} disabled={locating}>
          {locating ? <LoaderCircle className="location-spinner" size={16} /> : <Crosshair size={16} />}Use my current location
        </button>
        <span className="location-map__attribution">Map data © OpenStreetMap contributors</span>
      </div>
      {reverseSearching && <p className="location-hint" role="status">Looking up place name…</p>}
      {error && <p className="location-error" role="alert">{error}</p>}
    </section>
  );
}