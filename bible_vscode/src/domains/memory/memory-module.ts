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
import { CMD_COPY_LOAD_CMD, disposeLoadedContextBar } from './commands/_memory-actions';

export class MemoryModule implements DomainModule {
  readonly id = 'memory' as const;

  capabilities(): CapabilityManifest {
    return {
      required: [
        { command: ['memory', 'search'] },
      ],
      optional: [
        { command: ['memory', 'upload'],    featureFlag: 'memory.write' },
        { command: ['memory', 'download'],  featureFlag: 'memory.download' },
        { command: ['task', 'get'],         featureFlag: 'memory.taskPoll' },
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

    // 状态栏复制命令：点击状态栏 "Memory: xxx" 条目时触发
    disposables.push(
      vscode.commands.registerCommand(CMD_COPY_LOAD_CMD, async () => {
        const LOAD_CMD = '@bible-memory /load';
        await vscode.env.clipboard.writeText(LOAD_CMD);
        void deps.notify.info(`Copied: ${LOAD_CMD}  — paste in Chat, add your question, then send.`);
      }),
    );

    // 状态栏 item 生命周期（扩展停用时回收）
    disposables.push({ dispose: disposeLoadedContextBar });

    // Chat Participant
    disposables.push(registerMemoryParticipant(ctx, deps, service));

    return disposables;
  }
}
