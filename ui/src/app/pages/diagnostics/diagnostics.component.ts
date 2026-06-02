import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  DiagnosticsService,
  LogEntry,
  SystemStats,
} from '../../services/diagnostics.service';
import { DropdownComponent, DropdownOption } from '../../shared/dropdown/dropdown.component';

@Component({
  selector: 'app-diagnostics',
  standalone: true,
  imports: [CommonModule, FormsModule, DropdownComponent],
  templateUrl: './diagnostics.component.html',
  styleUrl: './diagnostics.component.scss',
})
export class DiagnosticsComponent implements OnInit {
  private diagService = inject(DiagnosticsService);

  stats: SystemStats | null = null;
  logs: LogEntry[] = [];
  filterCategory = '';
  filterCorrelationId = '';
  filterLevel: string | number = '';
  levelCategory = '';
  levelValue: string | number = 'DEBUG';

  logLevelFilterOptions: DropdownOption[] = [
    { value: '', label: 'All levels' },
    { value: 'DEBUG', label: 'DEBUG' },
    { value: 'INFO', label: 'INFO' },
    { value: 'WARNING', label: 'WARNING' },
    { value: 'ERROR', label: 'ERROR' },
    { value: 'CRITICAL', label: 'CRITICAL' },
  ];

  logLevelOptions: DropdownOption[] = [
    { value: 'DEBUG', label: 'DEBUG' },
    { value: 'INFO', label: 'INFO' },
    { value: 'WARNING', label: 'WARNING' },
    { value: 'ERROR', label: 'ERROR' },
  ];

  ngOnInit(): void {
    this.diagService.getStats().subscribe((s) => (this.stats = s));
    this.searchLogs();
  }

  searchLogs(): void {
    const params: Record<string, string | number> = { limit: 200 };
    if (this.filterCategory) params['category'] = this.filterCategory;
    if (this.filterCorrelationId) params['correlation_id'] = this.filterCorrelationId;
    if (this.filterLevel) params['level'] = this.filterLevel;
    this.diagService.getLogs(params).subscribe((l) => (this.logs = l));
  }

  setLogLevel(): void {
    if (this.levelCategory) {
      this.diagService.setLogLevel(this.levelCategory, this.levelValue as string).subscribe();
    }
  }
}
