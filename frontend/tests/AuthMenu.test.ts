// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthenticationSession } from "../src/types/auth";
import AuthMenu from "../src/components/AuthMenu.vue";

const authApi = vi.hoisted(() => ({
  startEmailLogin: vi.fn(),
  verifyEmailLogin: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("../src/api/auth", () => authApi);

const anonymous: AuthenticationSession = {
  schema_version: "1",
  authenticated: false,
};
const authenticated: AuthenticationSession = {
  schema_version: "1",
  authenticated: true,
  user: {
    id: "7ca9f85d-b16f-470b-a6a8-ab6d8582eb36",
    email: "member@example.test",
  },
  csrfToken: "csrf-token",
};

afterEach(() => {
  vi.resetAllMocks();
  document.body.classList.remove("auth-open");
});

describe("AuthMenu", () => {
  it("completes email-code login and emits the session", async () => {
    authApi.startEmailLogin.mockResolvedValue({
      schema_version: "1",
      accepted: true,
      message: "A code has been sent.",
    });
    authApi.verifyEmailLogin.mockResolvedValue(authenticated);
    const wrapper = mount(AuthMenu, {
      props: { session: anonymous },
      attachTo: document.body,
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get("button.auth-button").trigger("click");
    await wrapper.get("#login-email").setValue("member@example.test");
    await wrapper.get("form.auth-form").trigger("submit");
    await flushPromises();
    await wrapper.get("#login-code").setValue("12345678");
    await wrapper.get("form.auth-form").trigger("submit");
    await flushPromises();

    expect(authApi.startEmailLogin).toHaveBeenCalledWith(
      "member@example.test",
    );
    expect(authApi.verifyEmailLogin).toHaveBeenCalledWith(
      "member@example.test",
      "12345678",
    );
    expect(wrapper.emitted("sessionChanged")).toEqual([[authenticated]]);
    expect(wrapper.find(".auth-sheet").exists()).toBe(false);
    wrapper.unmount();
  });

  it("asks for confirmation before logging out an authenticated user", async () => {
    authApi.logout.mockResolvedValue(undefined);
    const wrapper = mount(AuthMenu, {
      props: { session: authenticated },
      attachTo: document.body,
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get("button.auth-button--secondary").trigger("click");

    expect(authApi.logout).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alertdialog"]').text()).toContain("Sign out?");

    await wrapper
      .get(".confirmation-actions button.button-primary")
      .trigger("click");
    await flushPromises();

    expect(authApi.logout).toHaveBeenCalledOnce();
    expect(wrapper.emitted("sessionChanged")).toEqual([
      [{ schema_version: "1", authenticated: false }],
    ]);
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("cancels sign out without changing the session", async () => {
    const wrapper = mount(AuthMenu, {
      props: { session: authenticated },
      attachTo: document.body,
      global: { stubs: { Teleport: true } },
    });

    await wrapper.get("button.auth-button--secondary").trigger("click");
    await wrapper
      .get(".confirmation-actions button.button-secondary")
      .trigger("click");
    await flushPromises();

    expect(authApi.logout).not.toHaveBeenCalled();
    expect(wrapper.emitted("sessionChanged")).toBeUndefined();
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
