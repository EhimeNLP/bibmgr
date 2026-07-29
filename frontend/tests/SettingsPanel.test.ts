// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPanel from "../src/components/SettingsPanel.vue";

const apiMocks = vi.hoisted(() => ({
  deleteExportProfile: vi.fn(),
  deleteVenue: vi.fn(),
  getApplicationConfiguration: vi.fn(),
  getConfigurationHistory: vi.fn(),
  updateExportProfile: vi.fn(),
  updateVenue: vi.fn(),
}));

vi.mock("../src/api/configuration", () => apiMocks);

const configuration = {
  schema_version: "1" as const,
  export_profiles: [
    {
      key: "laboratory",
      data: {
        schema_version: "1" as const,
        profile: "laboratory",
        display_name: "Laboratory",
        description: "Laboratory output.",
        validation_profile: "laboratory",
        preprint_representation: "misc-eprint",
      },
      revision: 0,
      built_in: true,
      updated_at: null,
      updated_by: null,
    },
  ],
  venues: [
    {
      key: "acl-annual-meeting",
      data: {
        id: "acl-annual-meeting",
        full_name: "Annual Meeting of the Association for Computational Linguistics",
        short_name: "ACL",
        aliases: ["Proceedings of ACL"],
        kind: "conference" as const,
      },
      revision: 0,
      built_in: true,
      updated_at: null,
      updated_by: null,
    },
  ],
};

beforeEach(() => {
  apiMocks.deleteExportProfile.mockReset();
  apiMocks.deleteVenue.mockReset();
  apiMocks.getApplicationConfiguration.mockReset();
  apiMocks.getConfigurationHistory.mockReset();
  apiMocks.updateExportProfile.mockReset();
  apiMocks.updateVenue.mockReset();
  apiMocks.getApplicationConfiguration.mockResolvedValue(
    structuredClone(configuration),
  );
  apiMocks.getConfigurationHistory.mockResolvedValue({
    schema_version: "1",
    kind: "export_profile",
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
  apiMocks.updateExportProfile.mockResolvedValue({
    schema_version: "1",
    setting: configuration.export_profiles[0],
  });
  apiMocks.updateVenue.mockResolvedValue({
    schema_version: "1",
    setting: configuration.venues[0],
  });
  apiMocks.deleteExportProfile.mockResolvedValue({
    schema_version: "1",
    key: "custom-profile",
    revision: 2,
    reset: false,
  });
  apiMocks.deleteVenue.mockResolvedValue({
    schema_version: "1",
    key: "custom-venue",
    revision: 2,
    reset: false,
  });
});

describe("SettingsPanel", () => {
  it("adds an export profile from a copied definition", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    await wrapper.get('[aria-label="Add export profile"]').trigger("click");
    await wrapper
      .get(".settings-field--identifier input")
      .setValue("lab-compact");
    await wrapper.get("form.settings-editor").trigger("submit");
    await flushPromises();

    expect(apiMocks.updateExportProfile).toHaveBeenCalledWith(
      { key: "lab-compact", revision: 0 },
      expect.objectContaining({
        profile: "lab-compact",
        display_name: "Laboratory Copy",
      }),
    );
    expect(wrapper.emitted("changed")).toHaveLength(1);

    wrapper.unmount();
  });

  it("adds a venue mapping", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    await wrapper.get('[role="tab"]:nth-child(2)').trigger("click");
    await wrapper.get('[aria-label="Add venue mapping"]').trigger("click");
    const fields = wrapper.findAll(".settings-editor input");
    await fields[0].setValue("new-nlp");
    await fields[1].setValue("New NLP Conference");
    await fields[2].setValue("NNLP");
    await wrapper.get("form.settings-editor").trigger("submit");
    await flushPromises();

    expect(apiMocks.updateVenue).toHaveBeenCalledWith(
      { key: "new-nlp", revision: 0 },
      expect.objectContaining({
        id: "new-nlp",
        full_name: "New NLP Conference",
        short_name: "NNLP",
      }),
    );

    wrapper.unmount();
  });

  it("edits a shared export profile with its loaded revision", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    const profile = {
      ...configuration.export_profiles[0].data,
      description: "Updated laboratory output.",
    };
    await wrapper
      .get(".settings-field--code textarea")
      .setValue(JSON.stringify(profile));
    await wrapper.get("form.settings-editor").trigger("submit");
    await flushPromises();

    expect(apiMocks.updateExportProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "laboratory",
        revision: 0,
      }),
      expect.objectContaining({
        profile: "laboratory",
        description: "Updated laboratory output.",
      }),
    );
    expect(wrapper.emitted("changed")).toHaveLength(1);

    wrapper.unmount();
  });

  it("does not offer to save an unchanged export profile", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();

    const save = wrapper.get('button[type="submit"]');
    expect(save.attributes("disabled")).toBeDefined();
    await wrapper.get("form.settings-editor").trigger("submit");

    expect(apiMocks.updateExportProfile).not.toHaveBeenCalled();

    wrapper.unmount();
  });

  it("edits a shared venue mapping with its loaded revision", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    await wrapper
      .get('[role="tab"]:nth-child(2)')
      .trigger("click");
    await wrapper.get('input[required]').setValue(
      "ACL Annual Meeting",
    );
    await wrapper.get("form.settings-editor").trigger("submit");
    await flushPromises();

    expect(apiMocks.updateVenue).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "acl-annual-meeting",
        revision: 0,
      }),
      expect.objectContaining({
        id: "acl-annual-meeting",
        full_name: "ACL Annual Meeting",
        short_name: "ACL",
      }),
    );
    expect(wrapper.emitted("changed")).toHaveLength(1);

    wrapper.unmount();
  });

  it("does not offer to save an unchanged venue mapping", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    await wrapper.get('[role="tab"]:nth-child(2)').trigger("click");

    const save = wrapper.get('button[type="submit"]');
    expect(save.attributes("disabled")).toBeDefined();
    await wrapper.get("form.settings-editor").trigger("submit");

    expect(apiMocks.updateVenue).not.toHaveBeenCalled();

    wrapper.unmount();
  });

  it("confirms and deletes a custom export profile", async () => {
    const customProfile = {
      ...structuredClone(configuration.export_profiles[0]),
      key: "custom-profile",
      revision: 1,
      built_in: false,
      data: {
        ...structuredClone(configuration.export_profiles[0].data),
        profile: "custom-profile",
        display_name: "Custom Profile",
      },
    };
    apiMocks.getApplicationConfiguration
      .mockResolvedValueOnce({
        ...structuredClone(configuration),
        export_profiles: [
          ...structuredClone(configuration.export_profiles),
          customProfile,
        ],
      })
      .mockResolvedValueOnce(structuredClone(configuration));
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    const customButton = wrapper
      .findAll(".settings-list__items button")
      .find((button) => button.text().includes("Custom Profile"));
    expect(customButton).toBeDefined();
    await customButton!.trigger("click");
    await wrapper.get(".button-danger-quiet").trigger("click");
    expect(wrapper.get(".settings-confirm").text()).toContain(
      "Delete this profile?",
    );
    expect(
      wrapper
        .get(".settings-confirm")
        .element.compareDocumentPosition(
          wrapper.get(".settings-field--code").element,
        ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await wrapper.get(".settings-confirm .button-danger").trigger("click");
    await flushPromises();

    expect(apiMocks.deleteExportProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "custom-profile",
        revision: 1,
      }),
    );
    expect(wrapper.emitted("changed")).toHaveLength(1);

    wrapper.unmount();
  });

  it("restores an edited built-in profile to its default", async () => {
    const editedProfile = {
      ...structuredClone(configuration.export_profiles[0]),
      revision: 1,
      data: {
        ...structuredClone(configuration.export_profiles[0].data),
        description: "Shared override.",
      },
    };
    apiMocks.getApplicationConfiguration
      .mockResolvedValueOnce({
        ...structuredClone(configuration),
        export_profiles: [editedProfile],
      })
      .mockResolvedValueOnce(structuredClone(configuration));
    apiMocks.deleteExportProfile.mockResolvedValueOnce({
      schema_version: "1",
      key: "laboratory",
      revision: 2,
      reset: true,
    });
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    expect(wrapper.get(".settings-editor__heading").text()).toContain(
      "Shared override, revision 1",
    );
    await wrapper
      .get(".settings-editor__actions .button-secondary")
      .trigger("click");
    expect(wrapper.get(".settings-confirm").text()).toContain(
      "Restore the built-in profile?",
    );
    await wrapper.get(".settings-confirm .button-primary").trigger("click");
    await flushPromises();

    expect(apiMocks.deleteExportProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "laboratory",
        revision: 1,
      }),
    );
    expect(wrapper.get(".settings-editor__heading").text()).toContain(
      "Built-in profile · Default",
    );
    expect(wrapper.text()).toContain(
      "laboratory was restored to its built-in definition.",
    );

    wrapper.unmount();
  });

  it("shows auditable history including deleted settings", async () => {
    apiMocks.getConfigurationHistory.mockResolvedValueOnce({
      schema_version: "1",
      kind: "export_profile",
      items: [
        {
          id: "66fb7ea4-8779-4b84-8b5c-f26f1192e101",
          key: "retired-profile",
          revision: 2,
          action: "delete",
          before_data: {
            profile: "retired-profile",
            display_name: "Retired Profile",
          },
          after_data: null,
          occurred_at: "2026-07-30T10:15:00Z",
          actor: {
            id: "66fb7ea4-8779-4b84-8b5c-f26f1192e102",
            email: "member@ai.cs.ehime-u.ac.jp",
          },
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    await wrapper
      .get('[aria-label="View export profile history"]')
      .trigger("click");
    await flushPromises();

    expect(apiMocks.getConfigurationHistory).toHaveBeenCalledWith(
      "export_profile",
      { limit: 50, offset: 0 },
    );
    expect(wrapper.get(".settings-history").text()).toContain(
      "retired-profile",
    );
    expect(wrapper.get(".settings-history").text()).toContain("Deleted");
    expect(wrapper.get(".settings-history").text()).toContain(
      "member@ai.cs.ehime-u.ac.jp",
    );
    await wrapper.get(".settings-history details").trigger("click");
    const diff = wrapper.get(".unified-diff");
    expect(diff.text()).toContain("Revision 1 → Deleted");
    expect(diff.text()).toContain(
      '"display_name": "Retired Profile"',
    );
    expect(wrapper.findAll(".unified-diff .is-deletion").length).toBeGreaterThan(
      0,
    );

    await wrapper.get(".settings-history .button-secondary").trigger("click");
    await wrapper.get('[role="tab"]:nth-child(2)').trigger("click");
    await wrapper
      .get('[aria-label="View venue mapping history"]')
      .trigger("click");
    await flushPromises();
    expect(apiMocks.getConfigurationHistory).toHaveBeenLastCalledWith(
      "venue",
      { limit: 50, offset: 0 },
    );
    expect(wrapper.get("#settings-history-heading").text()).toBe(
      "Venue mapping history",
    );

    wrapper.unmount();
  });

  it("labels an update from its previous revision to its new revision", async () => {
    apiMocks.getConfigurationHistory.mockResolvedValueOnce({
      schema_version: "1",
      kind: "export_profile",
      items: [
        {
          id: "profile-update",
          key: "laboratory",
          revision: 2,
          action: "update",
          before_data: {
            profile: "laboratory",
            description: "Revision one.",
          },
          after_data: {
            profile: "laboratory",
            description: "Revision two.",
          },
          occurred_at: "2026-07-30T10:15:00Z",
          actor: {
            id: "66fb7ea4-8779-4b84-8b5c-f26f1192e102",
            email: "member@ai.cs.ehime-u.ac.jp",
          },
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    await wrapper
      .get('[aria-label="View export profile history"]')
      .trigger("click");
    await flushPromises();
    await wrapper.get(".settings-history details").trigger("click");

    expect(wrapper.get(".settings-history .unified-diff").text()).toContain(
      "Revision 1 → Revision 2",
    );

    wrapper.unmount();
  });

  it.each([
    {
      section: "export profile",
      kind: "export_profile",
      historyLabel: "View export profile history",
      key: "laboratory",
      before: {
        profile: "laboratory",
        display_name: "Laboratory",
        description: "Original profile description.",
      },
      after: {
        description: "Updated profile description.",
        display_name: "Laboratory",
        profile: "laboratory",
      },
      removed: '"description": "Original profile description."',
      added: '"description": "Updated profile description."',
    },
    {
      section: "venue mapping",
      kind: "venue",
      historyLabel: "View venue mapping history",
      key: "acl-annual-meeting",
      before: {
        id: "acl-annual-meeting",
        full_name:
          "Annual Meeting of the Association for Computational Linguistics",
        short_name: "ACL",
        aliases: ["Proceedings of ACL"],
        kind: "conference",
      },
      after: {
        kind: "conference",
        aliases: ["Proceedings of ACL"],
        short_name: "ACL Annual",
        full_name:
          "Annual Meeting of the Association for Computational Linguistics",
        id: "acl-annual-meeting",
      },
      removed: '"short_name": "ACL"',
      added: '"short_name": "ACL Annual"',
    },
  ])(
    "shows only the actual $section override in its diff",
    async ({
      kind,
      historyLabel,
      key,
      before,
      after,
      removed,
      added,
    }) => {
      apiMocks.getConfigurationHistory.mockResolvedValueOnce({
        schema_version: "1",
        kind,
        items: [
          {
            id: `event-${kind}`,
            key,
            revision: 1,
            action: "override",
            before_data: before,
            after_data: after,
            occurred_at: "2026-07-30T10:15:00Z",
            actor: {
              id: "66fb7ea4-8779-4b84-8b5c-f26f1192e102",
              email: "member@ai.cs.ehime-u.ac.jp",
            },
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });
      const wrapper = mount(SettingsPanel, {
        props: { authenticated: true },
        global: { stubs: { Teleport: true } },
      });

      await wrapper.get(".settings-trigger").trigger("click");
      await flushPromises();
      if (kind === "venue") {
        await wrapper.get('[role="tab"]:nth-child(2)').trigger("click");
      }
      await wrapper
        .get(`[aria-label="${historyLabel}"]`)
        .trigger("click");
      await flushPromises();
      await wrapper.get(".settings-history details").trigger("click");

      const diff = wrapper.get(".settings-history .unified-diff");
      const additions = diff.findAll(".is-addition");
      const deletions = diff.findAll(".is-deletion");
      expect(diff.text()).toContain("Built-in default → Revision 1");
      expect(additions).toHaveLength(1);
      expect(deletions).toHaveLength(1);
      expect(additions[0]?.text()).toContain(added);
      expect(deletions[0]?.text()).toContain(removed);

      wrapper.unmount();
    },
  );

  it("does not invent a diff for a legacy override without a before snapshot", async () => {
    apiMocks.getConfigurationHistory.mockResolvedValueOnce({
      schema_version: "1",
      kind: "export_profile",
      items: [
        {
          id: "legacy-override",
          key: "laboratory",
          revision: 1,
          action: "override",
          before_data: null,
          after_data: configuration.export_profiles[0].data,
          occurred_at: "2026-07-30T10:15:00Z",
          actor: {
            id: "66fb7ea4-8779-4b84-8b5c-f26f1192e102",
            email: "member@ai.cs.ehime-u.ac.jp",
          },
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: true },
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get(".settings-trigger").trigger("click");
    await flushPromises();
    await wrapper
      .get('[aria-label="View export profile history"]')
      .trigger("click");
    await flushPromises();
    await wrapper.get(".settings-history details").trigger("click");

    expect(wrapper.find(".settings-history .unified-diff").exists()).toBe(
      false,
    );
    expect(wrapper.get(".settings-history__unavailable").text()).toContain(
      "exact diff is unavailable",
    );

    wrapper.unmount();
  });

  it("requests login instead of opening settings anonymously", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { authenticated: false },
    });

    await wrapper.get(".settings-trigger").trigger("click");

    expect(wrapper.emitted("loginRequired")).toHaveLength(1);
    expect(apiMocks.getApplicationConfiguration).not.toHaveBeenCalled();
  });
});
