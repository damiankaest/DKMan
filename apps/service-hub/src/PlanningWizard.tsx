import { useEffect, useState } from 'react';
import { ApiClient, type AppItem } from './api';
import type { components } from './generated/api';

type Requirements = components['schemas']['Requirements'];
const split = (value: string) => value.split('\n').map(item => item.trim()).filter(Boolean);

export function PlanningWizard({api, initial, onApply, onCancel}: {api: ApiClient; initial: Requirements; onApply: (value: Requirements) => void; onCancel: () => void}) {
  const [step, setStep] = useState(0);
  const [title, setTitle] = useState(initial.title);
  const [goal, setGoal] = useState(initial.goal);
  const [features, setFeatures] = useState(initial.features.join('\n'));
  const [entities, setEntities] = useState((initial.entities ?? []).join('\n'));
  const [screens, setScreens] = useState((initial.screens ?? []).join('\n'));
  const [acceptance, setAcceptance] = useState((initial.acceptance_checks ?? []).join('\n'));
  const [operation, setOperation] = useState((initial.deployment_requirements ?? []).join('\n'));
  const [apps, setApps] = useState<AppItem[]>([]);
  const [error, setError] = useState('');
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    if (step !== 2) return;
    const controller = new AbortController();
    setChecked(false); setError('');
    void api.apps(controller.signal).then(items => {if (!controller.signal.aborted) {setApps(items);setChecked(true);}}).catch(() => {if (!controller.signal.aborted) setError('Vorhandene Apps konnten nicht geladen werden. Du kannst trotzdem fortfahren.');});
    return () => controller.abort();
  }, [api,step]);
  function next() {
    const values = [features,entities,screens,acceptance,operation];
    if (values.some(value => split(value).length > 30 || split(value).some(line => line.length > 500))) {setError('Höchstens 30 Einträge pro Feld und 500 Zeichen pro Eintrag.');return;}
    setError('');setStep(step + 1);
  }
  function add(app: AppItem) {
    const line = `Integration prüfen: ${app.name} [${app.definition_id}]`;
    if (line.length > 500 || split(operation).length >= 30) {setError('Prüfauftrag passt nicht in die Betriebsanforderungen.');return;}
    setOperation([...new Set([...split(operation),line])].join('\n'));
  }
  return <section className="planning-wizard" aria-label="Geführte Planung">
    <h3>App-Idee Schritt für Schritt</h3><p role="status">Schritt {step + 1} von 4: {['Ziel','Funktionen und Daten','Vorhandene Apps','Prüfen'][step]}</p>
    <p>Dein Entwurf wird erst nach der Übernahme und dem anschließenden Speichern dauerhaft abgelegt.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {step === 0 && <><button type="button" onClick={() => {if (!title && !goal && !features && !entities && !screens && !acceptance && !operation) {setTitle('Unser Garten');setGoal('Den Garten gemeinsam planen und Pflanzen pflegen.');setFeatures('Pflanzen mit Fotos verwalten\nGießen und Düngen planen\nGarten im 2D-Plan darstellen');setEntities('Pflanze\nBeet\nPflegeaufgabe');setScreens('Gartenplan\nPflanzenübersicht\nPflegekalender');setAcceptance('Pflanzen bleiben nach dem Neuladen erhalten');}}}>Garten-Beispiel einfügen</button><label htmlFor="w-title">Name</label><input id="w-title" maxLength={120} value={title} onChange={e => setTitle(e.target.value)} /><label htmlFor="w-goal">Ziel</label><textarea id="w-goal" maxLength={4000} value={goal} onChange={e => setGoal(e.target.value)} /></>}
    {step === 1 && <><label htmlFor="w-features">Funktionen · ein Eintrag pro Zeile</label><textarea id="w-features" value={features} onChange={e => setFeatures(e.target.value)} /><label htmlFor="w-entities">Daten und Entitäten</label><textarea id="w-entities" value={entities} onChange={e => setEntities(e.target.value)} /><label htmlFor="w-screens">Ansichten</label><textarea id="w-screens" value={screens} onChange={e => setScreens(e.target.value)} /></>}
    {step === 2 && <><p>Diese für dich sichtbaren Apps kannst du als mögliche Integration prüfen. Eine Auswahl verbindet keine Daten und erteilt keine Freigabe.</p>{checked && apps.length === 0 && <p>Keine Apps für dich sichtbar.</p>}<ul>{apps.map(app => <li key={app.id}><strong>{app.name}</strong> · {app.description}<button type="button" onClick={() => add(app)}>Integration von {app.name} prüfen</button></li>)}</ul><label htmlFor="w-operation">Anforderungen an den Betrieb</label><textarea id="w-operation" value={operation} onChange={e => setOperation(e.target.value)} /></>}
    {step === 3 && <><h4>{title}</h4><p>{goal}</p><ul>{split(features).map((item,index) => <li key={index}>{item}</li>)}</ul><p>{split(operation).join(' · ')}</p><label htmlFor="w-acceptance">Abnahmekriterien</label><textarea id="w-acceptance" value={acceptance} onChange={e => setAcceptance(e.target.value)} /><button type="button" onClick={() => {const lists=[features,entities,screens,acceptance,operation];if (lists.some(value => split(value).length > 30 || split(value).some(line => line.length > 500))) {setError('Höchstens 30 Einträge pro Feld und 500 Zeichen pro Eintrag.');return;}onApply({title:title.trim(),goal:goal.trim(),features:split(features),entities:split(entities),screens:split(screens),acceptance_checks:split(acceptance),deployment_requirements:split(operation)});}}>In Planung übernehmen</button></>}
    {step > 0 && <button type="button" onClick={() => {setError('');setStep(step - 1);}}>Zurück</button>}
    {step < 3 && <button type="button" onClick={next} disabled={(step === 0 && (!title.trim() || !goal.trim())) || (step === 1 && !features.trim())}>Weiter</button>}
    <button type="button" onClick={onCancel}>Wizard schließen</button>
  </section>;
}
