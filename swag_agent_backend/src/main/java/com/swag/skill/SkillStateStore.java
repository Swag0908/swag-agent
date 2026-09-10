package com.swag.skill;

import java.util.Set;

/**
 * 技能启停状态的持久化接口。
 * <p>
 * 技能正文来自磁盘，启停状态才是需要落库的部分：进程重启、多实例部署、换机器后
 * 管理端设置过的启停都应保持。默认语义是"表里没有该技能 = 启用"，因此新装的技能开箱即用，
 * 只有被显式停用过的技能才会出现在表里（enabled = 0）。
 */
public interface SkillStateStore {

    /** 被显式停用的技能名集合。 */
    Set<String> disabledSkills();

    /** 记录一个技能的启停状态（重复设置覆盖）。 */
    void setEnabled(String name, boolean enabled);

    /** 技能被删除时清理它的状态行。 */
    void remove(String name);

    /**
     * 清理已不存在的技能留下的历史状态行，返回清理条数。
     * 传入空集合时不做任何清理（技能全丢更可能是扫描失败，不能顺手清空管理员设置）。
     */
    int removeMissing(Set<String> existingNames);
}
