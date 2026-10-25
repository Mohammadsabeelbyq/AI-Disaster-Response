import { useEffect, useState } from 'react';
import { AlertCircle, Check, LoaderCircle, Plus, Save } from 'lucide-react';
import {
  createDepartment,
  createResource,
  listDepartments,
  listResources,
  updateDepartment,
  updateResource,
  updateResourceAvailability,
} from '../../api/resources.js';
import { useAuth } from '../auth/AuthProvider.jsx';

const departmentTypes = ['FIRE', 'MEDICAL', 'POLICE', 'DISASTER_MANAGEMENT'];
const resourceTypes = ['RESCUE_TEAM', 'VEHICLE', 'SHELTER', 'SUPPLY'];
const availabilityTypes = ['AVAILABLE', 'UNAVAILABLE', 'MAINTENANCE'];

const blankDepartment = { code: '', name: '', department_type: 'FIRE' };
const blankResource = {
  code: '',
  department_id: '',
  resource_type: 'RESCUE_TEAM',
  name: '',
  capabilities: '',
  latitude: '',
  longitude: '',
  availability: 'AVAILABLE',
};

function statusLabel(value) {
  return value.replaceAll('_', ' ');
}

export default function ResourceRegistryPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const [departments, setDepartments] = useState([]);
  const [resources, setResources] = useState([]);
  const [departmentDraft, setDepartmentDraft] = useState(blankDepartment);
  const [resourceDraft, setResourceDraft] = useState(blankResource);
  const [editingResourceId, setEditingResourceId] = useState(null);
  const [availabilityDrafts, setAvailabilityDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  async function refreshRegistry() {
    const [nextDepartments, nextResources] = await Promise.all([
      listDepartments(),
      listResources(),
    ]);
    setDepartments(nextDepartments);
    setResources(nextResources);
    setResourceDraft((current) => ({
      ...current,
      department_id: nextDepartments.some((item) => item.id === current.department_id && item.is_active)
        ? current.department_id : nextDepartments.find((item) => item.is_active)?.id || '',
    }));
    setAvailabilityDrafts((current) => Object.fromEntries(nextResources.map((resource) => [
      resource.id,
      current[resource.id] || { availability: resource.availability, reason: '' },
    ])));
  }

  useEffect(() => {
    let active = true;
    Promise.all([listDepartments(), listResources()])
      .then(([nextDepartments, nextResources]) => {
        if (!active) return;
        setDepartments(nextDepartments);
        setResources(nextResources);
        setResourceDraft((current) => ({
          ...current,
          department_id: current.department_id || nextDepartments.find((item) => item.is_active)?.id || '',
        }));
      })
      .catch((error) => active && setMessage({ kind: 'error', text: error.message }))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  async function saveDepartment(event) {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      await createDepartment(departmentDraft);
      setDepartmentDraft(blankDepartment);
      await refreshRegistry();
      setMessage({ kind: 'success', text: 'Department saved to the registry.' });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setSaving(false);
    }
  }

  function startEditing(resource) {
    setEditingResourceId(resource.id);
    setResourceDraft({
      code: resource.code,
      department_id: resource.department_id,
      resource_type: resource.resource_type,
      name: resource.name,
      capabilities: resource.capabilities.join(', '),
      latitude: String(resource.latitude),
      longitude: String(resource.longitude),
      availability: resource.availability,
    });
    setMessage(null);
  }

  async function saveResource(event) {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    const payload = {
      ...resourceDraft,
      capabilities: resourceDraft.capabilities.split(',').map((item) => item.trim()).filter(Boolean),
      latitude: Number(resourceDraft.latitude),
      longitude: Number(resourceDraft.longitude),
    };
    try {
      if (editingResourceId) {
        const { code, availability, ...details } = payload;
        await updateResource(editingResourceId, details);
      } else {
        await createResource(payload);
      }
      setResourceDraft({
        ...blankResource,
        department_id: departments.find((department) => department.is_active)?.id || '',
      });
      setEditingResourceId(null);
      await refreshRegistry();
      setMessage({ kind: 'success', text: editingResourceId
        ? 'Resource details updated.' : 'Resource registered successfully.' });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setSaving(false);
    }
  }

  async function saveAvailability(resource) {
    const draft = availabilityDrafts[resource.id];
    if (!draft?.reason.trim()) {
      setMessage({ kind: 'error', text: 'Add a reason for the availability change.' });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await updateResourceAvailability(resource.id, draft.availability, draft.reason.trim());
      setAvailabilityDrafts((current) => ({
        ...current,
        [resource.id]: { availability: draft.availability, reason: '' },
      }));
      await refreshRegistry();
      setMessage({ kind: 'success', text: `Availability updated for ${resource.code}.` });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setSaving(false);
    }
  }

  async function toggleDepartment(department) {
    setSaving(true);
    setMessage(null);
    try {
      await updateDepartment(department.id, { is_active: !department.is_active });
      await refreshRegistry();
      setMessage({ kind: 'success', text: `${department.name} ${department.is_active ? 'deactivated' : 'activated'}.` });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <section className="page-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow__line" />OPERATIONAL CAPACITY</div>
          <h1>Resource registry<span className="heading-period">.</span></h1>
          <p>Persistent departments, response resources, locations and current availability.</p>
        </div>
      </section>

      {message && (
        <div className={`notice notice--${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.kind === 'error' ? <AlertCircle size={17} /> : <Check size={17} />}{message.text}
        </div>
      )}

      {loading ? (
        <div className="panel resource-state" role="status"><LoaderCircle className="location-spinner" size={20} />Loading registry…</div>
      ) : (
        <>
          {isAdmin && (
            <section className="resource-admin-grid">
              <form className="panel resource-form" onSubmit={saveDepartment}>
                <div className="panel-heading"><div><span className="section-kicker">MASTER DATA</span><h2>Add department</h2></div></div>
                <div className="field-grid">
                  <label className="field"><span>Department code</span><input required maxLength="30" value={departmentDraft.code} onChange={(event) => setDepartmentDraft({ ...departmentDraft, code: event.target.value })} placeholder="DEP-FIRE" /></label>
                  <label className="field"><span>Department type</span><select value={departmentDraft.department_type} onChange={(event) => setDepartmentDraft({ ...departmentDraft, department_type: event.target.value })}>{departmentTypes.map((type) => <option key={type} value={type}>{statusLabel(type)}</option>)}</select></label>
                </div>
                <label className="field"><span>Department name</span><input required maxLength="150" value={departmentDraft.name} onChange={(event) => setDepartmentDraft({ ...departmentDraft, name: event.target.value })} placeholder="Fire and Rescue" /></label>
                <button className="button button--primary resource-form__submit" type="submit" disabled={saving}><Plus size={15} />Add department</button>
                <ul className="resource-department-list">
                  {departments.map((department) => (
                    <li key={department.id}>
                      <span><strong>{department.code}</strong> · {department.name} <small>{statusLabel(department.department_type)} · {department.is_active ? 'ACTIVE' : 'INACTIVE'}</small></span>
                      <button className="button button--quiet" type="button" disabled={saving} onClick={() => toggleDepartment(department)}>{department.is_active ? 'Deactivate' : 'Activate'}</button>
                    </li>
                  ))}
                </ul>
              </form>

              <form className="panel resource-form" onSubmit={saveResource}>
                <div className="panel-heading"><div><span className="section-kicker">RESOURCE MASTER DATA</span><h2>{editingResourceId ? 'Edit resource' : 'Register resource'}</h2></div></div>
                <div className="field-grid">
                  <label className="field"><span>Unique resource code</span><input required maxLength="30" disabled={Boolean(editingResourceId)} value={resourceDraft.code} onChange={(event) => setResourceDraft({ ...resourceDraft, code: event.target.value })} placeholder="RES-BOAT-01" /></label>
                  <label className="field"><span>Resource type</span><select value={resourceDraft.resource_type} onChange={(event) => setResourceDraft({ ...resourceDraft, resource_type: event.target.value })}>{resourceTypes.map((type) => <option key={type} value={type}>{statusLabel(type)}</option>)}</select></label>
                </div>
                <label className="field"><span>Owning department</span><select required value={resourceDraft.department_id} onChange={(event) => setResourceDraft({ ...resourceDraft, department_id: event.target.value })}><option value="">Choose a department</option>{departments.filter((department) => department.is_active).map((department) => <option key={department.id} value={department.id}>{department.code} · {department.name}</option>)}</select></label>
                <label className="field"><span>Resource name</span><input required maxLength="150" value={resourceDraft.name} onChange={(event) => setResourceDraft({ ...resourceDraft, name: event.target.value })} placeholder="North rescue boat" /></label>
                <label className="field"><span>Capabilities <small>COMMA-SEPARATED TAGS</small></span><input required value={resourceDraft.capabilities} onChange={(event) => setResourceDraft({ ...resourceDraft, capabilities: event.target.value })} placeholder="RESCUE, WATER" /></label>
                <div className="field-grid">
                  <label className="field"><span>Latitude</span><input required type="number" min="-90" max="90" step="any" value={resourceDraft.latitude} onChange={(event) => setResourceDraft({ ...resourceDraft, latitude: event.target.value })} /></label>
                  <label className="field"><span>Longitude</span><input required type="number" min="-180" max="180" step="any" value={resourceDraft.longitude} onChange={(event) => setResourceDraft({ ...resourceDraft, longitude: event.target.value })} /></label>
                </div>
                {!editingResourceId && <label className="field"><span>Initial availability</span><select value={resourceDraft.availability} onChange={(event) => setResourceDraft({ ...resourceDraft, availability: event.target.value })}>{availabilityTypes.map((value) => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>}
                <div className="resource-form__actions">
                  <button className="button button--primary" type="submit" disabled={saving || !departments.some((department) => department.is_active)}><Save size={15} />{editingResourceId ? 'Save resource' : 'Register resource'}</button>
                  {editingResourceId && <button className="button button--quiet" type="button" onClick={() => { setEditingResourceId(null); setResourceDraft(blankResource); }}>Cancel edit</button>}
                </div>
              </form>
            </section>
          )}

          <section className="panel resource-list-panel">
            <div className="panel-heading">
              <div><span className="section-kicker">DATABASE RECORDS</span><h2>Registered resources</h2></div>
              <span className="results-total">{resources.length} total</span>
            </div>
            {resources.length === 0 ? (
              <div className="resource-state">No resources registered yet. An administrator can create departments and resources above.</div>
            ) : (
              <div className="resource-table">
                {resources.map((resource) => {
                  const draft = availabilityDrafts[resource.id] || { availability: resource.availability, reason: '' };
                  return (
                    <article className="resource-row" key={resource.id}>
                      <div className="resource-row__identity">
                        <strong>{resource.name}</strong><span>{resource.code} · {statusLabel(resource.resource_type)} · {resource.department.name}</span>
                        <span>{resource.latitude}, {resource.longitude}</span>
                        <div className="resource-capabilities">{resource.capabilities.map((capability) => <span key={capability}>{statusLabel(capability)}</span>)}</div>
                      </div>
                      <div className="resource-row__controls">
                        <span className={`resource-availability resource-availability--${resource.availability.toLowerCase()}`}>{statusLabel(resource.availability)}</span>
                        <label className="field"><span>Availability</span><select value={draft.availability} onChange={(event) => setAvailabilityDrafts((current) => ({ ...current, [resource.id]: { ...draft, availability: event.target.value } }))}>{availabilityTypes.map((value) => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>
                        <label className="field"><span>Reason for change</span><input value={draft.reason} onChange={(event) => setAvailabilityDrafts((current) => ({ ...current, [resource.id]: { ...draft, reason: event.target.value } }))} placeholder="Required when changing state" /></label>
                        <button className="button button--quiet" type="button" disabled={saving || draft.availability === resource.availability} onClick={() => saveAvailability(resource)}>Save status</button>
                        {isAdmin && <button className="button button--quiet" type="button" disabled={saving} onClick={() => startEditing(resource)}>Edit resource</button>}
                        <div className="resource-history">
                          {resource.availability_events.map((event) => (
                            <small key={event.id}>
                              {new Date(event.changed_at).toLocaleString()} · {event.previous_availability || 'CREATED'} → {event.new_availability} · {event.reason} · actor {event.changed_by}
                            </small>
                          ))}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
