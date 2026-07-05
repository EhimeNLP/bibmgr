import type { Reference } from "../types/reference";

export async function searchReferences(query: string): Promise<Reference[]> {
  console.log("Search query:", query);

  // TODO: Replace this mock implementation with a backend API call.
  // Example:
  // const response = await fetch(`/api/references?query=${encodeURIComponent(query)}`);
  // if (!response.ok) {
  //   throw new Error("Failed to search references");
  // }
  // return response.json();

  return [];
}
