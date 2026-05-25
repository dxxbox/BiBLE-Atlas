import * as vscode from 'vscode';
import { DomainModule, ModuleDeps } from '../types';
import { CapabilityManifest } from '../../core/registry/capability';
import { DefaultMemoryService, MemoryService } from './memory-service';
import { DefaultMemoryBuilder } from './memory-builder';
import { MemorySearchTool } from './tools/memory-search.tool';
import { MemoryImportTool } from './tools/memory-import.tool';
import { MemoryDownloadTool } from './tools/memory-download.tool';
import { registerSearchMemoryCommand } from './commands/search-memory.command';
import { registerSaveChatCommand } from './commands/save-chat.command';
import { registerShowLastImportFilesCommand } from './commands/show-last-import-files.command';
import { registerMemoryParticipant } from './participant/memory-participant';

export class MemoryModule implements DomainModule {
  readonly id = 'memory' as const;

  capabilities(): CapabilityManifest {
    return {
      required: [
        { command: ['memory', 'search'] },
      ],
      optional: [
        { command: ['memory', 'import'],          featureFlag: 'memory.write' },
        { command: ['memory', 'download', 'file'], featureFlag: 'memory.download' },
        { command: ['memory', 'artifact', 'fetch'], featureFlag: 'memory.artifact' },
      ],
    };
  }

  register(ctx: vscode.ExtensionContext, deps: ModuleDeps): vscode.Disposable[] {
    const builder = new DefaultMemoryBuilder(deps.config, deps.output);
    const service: MemoryService = new DefaultMemoryService({
      cli: deps.cli,
      config: deps.config,
      output: deps.output,
      builder,
      tasks: deps.tasks,
    });

    const disposables: vscode.Disposable[] = [];

    // Tools
    disposables.push(
      deps.toolRegistry.register(
        'bible_memory_search',
        new MemorySearchTool({ cli: deps.cli, output: deps.output }, {
          name: 'bible_memory_search',
          busyText: (i) => `Searching memory: ${i.query}`,
        }),
      ),
    );
    disposables.push(
      deps.toolRegistry.register(
        'bible_memory_import',
        new MemoryImportTool({
          service,
          tasks: deps.tasks,
          notify: deps.notify,
          output: deps.output,
          config: deps.config,
        }),
      ),
    );
    disposables.push(
      deps.toolRegistry.register(
        'bible_memory_download',
        new MemoryDownloadTool({
          service,
          tasks: deps.tasks,
          notify: deps.notify,
          output: deps.output,
          config: deps.config,
        }),
      ),
    );

    // Commands (面板可见的用户命令)
    disposables.push(registerSearchMemoryCommand(ctx, deps, service));
    disposables.push(registerSaveChatCommand(deps, service));
    // Hidden debug command (代码注册但 package.json 不暴露到命令面板；通过 keybinding/programmatic 调用)
    disposables.push(registerShowLastImportFilesCommand(deps));

    // Chat Participant
    disposables.push(registerMemoryParticipant(ctx, deps, service));

    return disposables;
  }
}
