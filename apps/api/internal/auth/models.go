package auth

import "time"

type userDTO struct {
	ID        string  `json:"id"`
	OrgID     string  `json:"org_id"`
	Email     string  `json:"email"`
	Name      string  `json:"name"`
	AvatarURL *string `json:"avatar_url"`
	Role      string  `json:"role"`
	CreatedAt time.Time `json:"created_at"`
}

func toUserDTO(u *User) userDTO {
	return userDTO{
		ID:        u.ID.String(),
		OrgID:     u.OrgID.String(),
		Email:     u.Email,
		Name:      u.Name,
		AvatarURL: u.AvatarURL,
		Role:      u.Role,
		CreatedAt: u.CreatedAt,
	}
}
