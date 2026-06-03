import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
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
  private route = inject(ActivatedRoute);

  stats: SystemStats | null = null;
  logs: LogEntry[] = [];
  filterCategory = '';
  filterCorrelationId = '';
  filterLevel: string | number = '';
  filterBotId: number | null = null;
  levelCategory = '*';
  levelValue: string | number = 'INFO';
  logLevelRules: { category: string; level: string }[] = [];

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
    const botId = this.route.snapshot.queryParamMap.get('bot_id');
    if (botId) {
      this.filterBotId = parseInt(botId, 10);
    }
    this.searchLogs();
    this.loadLogLevels();
  }

  searchLogs(): void {
    const params: Record<string, string | number> = { limit: 200 };
    if (this.filterCategory) params['category'] = this.filterCategory;
    if (this.filterCorrelationId) params['correlation_id'] = this.filterCorrelationId;
    if (this.filterLevel) params['level'] = this.filterLevel;
    if (this.filterBotId) params['bot_id'] = this.filterBotId;
    this.diagService.getLogs(params).subscribe((l) => (this.logs = l));
  }

  loadLogLevels(): void {
    this.diagService.getLogLevels().subscribe((levels) => {
      this.logLevelRules = Object.entries(levels).map(([category, level]) => ({
        category,
        level,
      }));
    });
  }

  setLogLevel(): void {
    if (this.levelCategory) {
      this.diagService
        .setLogLevel(this.levelCategory, this.levelValue as string)
        .subscribe(() => {
          this.loadLogLevels();
          this.levelCategory = '';
          this.levelValue = 'INFO';
        });
    }
  }

  removeLogLevel(category: string): void {
    this.diagService.removeLogLevel(category).subscribe(() => {
      this.loadLogLevels();
    });
  }
}
