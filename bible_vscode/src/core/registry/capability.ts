export interface CapabilityRequirement {
  /** CLI 命令路径，例：['memory', 'search'] */
  command: string[];
  /** 可选最低版本（CLI 实现 health 时附带语义化版本时启用） */
  minVersion?: string;
}

export interface OptionalCapability extends CapabilityRequirement {
  /** 特性开关名（例：'memory.write' / 'skill.download'） */
  featureFlag: string;
}

export interface CapabilityManifest {
  /** required 全部都要可用；任何一条不可用 → 整个域禁用 */
  required: CapabilityRequirement[];
  /** optional 控制具体 Tool/Command 启停 */
  optional: OptionalCapability[];
}

export interface CapabilityReport {
  domain: string;
  available: boolean;
  missingRequired: CapabilityRequirement[];
  enabledFlags: string[];
  disabledFlags: string[];
}
