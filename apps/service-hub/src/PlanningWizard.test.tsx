import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { PlanningWizard } from './PlanningWizard';

it('reviews a garden draft and a visible app before transferring the requirements', async () => {
  const apply = vi.fn();
  const api = {apps: vi.fn(async () => [{id:'one',definition_id:'notes',name:'Notes',description:'Notizen'}])} as unknown as ApiClient;
  render(<PlanningWizard api={api} initial={{title:'',goal:'',features:[]}} onApply={apply} onCancel={() => {}} />);
  expect(screen.getByRole('button',{name:'Weiter'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Garten-Beispiel einfügen'}));
  fireEvent.click(screen.getByRole('button',{name:'Weiter'}));
  fireEvent.click(screen.getByRole('button',{name:'Weiter'}));
  fireEvent.click(await screen.findByRole('button',{name:'Integration von Notes prüfen'}));
  expect(screen.getByLabelText('Anforderungen an den Betrieb')).toHaveValue('Integration prüfen: Notes [notes]');
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Weiter'}));
  fireEvent.click(screen.getByRole('button',{name:'In Planung übernehmen'}));
  expect(apply).toHaveBeenCalledWith(expect.objectContaining({title:'Unser Garten',deployment_requirements:['Integration prüfen: Notes [notes]']}));
});

it('retains edits across wizard navigation and rejects oversized entries', () => {
  const api = {apps: vi.fn(async () => [])} as unknown as ApiClient;
  render(<PlanningWizard api={api} initial={{title:'Garten',goal:'Pflegen',features:['Fotos']}} onApply={() => {}} onCancel={() => {}} />);
  fireEvent.click(screen.getByRole('button',{name:'Weiter'}));
  fireEvent.change(screen.getByLabelText('Funktionen · ein Eintrag pro Zeile'),{target:{value:'x'.repeat(501)}});
  fireEvent.click(screen.getByRole('button',{name:'Weiter'}));
  expect(screen.getByRole('alert')).toHaveTextContent('500 Zeichen');
  fireEvent.click(screen.getByRole('button',{name:'Zurück'}));
  expect(screen.getByLabelText('Name')).toHaveValue('Garten');
});
