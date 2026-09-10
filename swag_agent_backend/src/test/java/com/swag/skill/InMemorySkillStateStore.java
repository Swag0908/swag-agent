package com.swag.skill;

import java.util.LinkedHashSet;
import java.util.Set;

/**
 * 测试用内存实现：模拟 {@code skill_state} 表（只记录被显式停用的技能）。
 */
class InMemorySkillStateStore implements SkillStateStore {

    private final Set<String> disabled = new LinkedHashSet<>();

    @Override
    public Set<String> disabledSkills() {
        return Set.copyOf(disabled);
    }

    @Override
    public void setEnabled(String name, boolean enabled) {
        if (enabled) {
            disabled.remove(name);
        } else {
            disabled.add(name);
        }
    }

    @Override
    public void remove(String name) {
        disabled.remove(name);
    }

    @Override
    public int removeMissing(Set<String> existingNames) {
        if (existingNames == null || existingNames.isEmpty()) {
            return 0;
        }
        int before = disabled.size();
        disabled.retainAll(existingNames);
        return before - disabled.size();
    }
}
