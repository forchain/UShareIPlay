## ADDED Requirements

### Requirement: Command parsing MUST NOT mutate shared command configuration
命令解析器在解析单条输入时 **MUST NOT** 修改/污染共享的命令配置对象（例如命令配置列表中的 dict）。解析出的参数与解析结果 MUST 是“每条输入独立”的数据结构，保证并发与多入口注入场景下不会发生跨消息串台。

#### Scenario: Parsing does not leak parameters across messages
- **WHEN** 系统先后解析两条不同输入（例如 `help` 与 `play foo`），且两次解析匹配到不同命令或同一命令但参数不同
- **THEN** 第二次解析结果中的 `parameters` MUST 只反映第二条输入
- **AND THEN** 任何后续解析 MUST NOT 受到前一次解析写入的副作用影响

