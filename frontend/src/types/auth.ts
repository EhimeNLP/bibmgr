export type AuthenticatedUser = {
  id: string;
  email: string;
};

export type AuthenticationSession = {
  schema_version: "1";
  authenticated: boolean;
  user?: AuthenticatedUser;
  csrfToken?: string;
};

export type EmailLoginStartResult = {
  schema_version: "1";
  accepted: true;
  message: string;
};
